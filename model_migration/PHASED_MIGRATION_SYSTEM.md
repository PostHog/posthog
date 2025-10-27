# Phased Migration System

## Overview

A new migration system built with clean separation of concerns, phase tracking, and idempotent execution. Designed to replace the monolithic migrate_models.py with a more maintainable, debuggable approach.

## Architecture

```
model_migration/
├── move_scanner.py         # Auto-discovers structure, generates moves.yml
├── import_rewriter.py      # LibCST-based import transformation
├── phase_tracker.py        # State tracking module
├── migrate_phased.py       # Main orchestrator
├── moves.yml               # Generated: file moves & module mappings
└── phase_tracker.yml       # Generated: execution state
```

## Key Principles

1. **Separation of Concerns**: File movement and import updates are separate phases
2. **Idempotent**: Can resume from any phase, tracks state in phase_tracker.yml
3. **Declarative**: moves.yml is single source of truth for all transformations
4. **No Manual Fixes**: If it fails, improve the tool and retry (not manual cleanup)
5. **Shims Preserved**: Keeps 1:1 file structure during migration
6. **Validation at Each Step**: Uses Django --plan to verify correctness

## Tools

### 1. move_scanner.py

Auto-discovers file structure and generates moves.yml configuration.

```bash
python model_migration/move_scanner.py --product data_warehouse --output model_migration/moves.yml

# Or dry-run to see output:
python model_migration/move_scanner.py --product data_warehouse --dry-run
```

**Output:**
```yaml
product: data_warehouse
source: posthog.warehouse
target: products.data_warehouse.backend
file_moves:
  - from: posthog/warehouse/models/table.py
    to: products/data_warehouse/backend/models/table.py
  # ... 63 total
module_moves:
  posthog.warehouse: products.data_warehouse.backend
  posthog.warehouse.models: products.data_warehouse.backend.models
  # ... 9 total
symbol_remap: {}  # Currently empty (star imports not tracked)
```

### 2. import_rewriter.py

LibCST-based import transformation (adapted from libcst.md article).

```bash
# Dry run to see what would change:
python model_migration/import_rewriter.py --dry-run

# Apply changes:
python model_migration/import_rewriter.py --write

# Single file:
python model_migration/import_rewriter.py --file posthog/tasks/usage_report.py
```

**Example transformation:**
```python
# Before:
from posthog.warehouse.models import DataWarehouseTable, ExternalDataJob

# After:
from products.data_warehouse.backend.models import DataWarehouseTable, ExternalDataJob
```

**Features:**
- Handles relative imports (converts to absolute)
- Preserves aliases (`import X as Y`)
- Multi-split imports (when symbols map to different modules)
- Respects TYPE_CHECKING blocks
- Handles lazy imports in functions

### 3. migrate_phased.py

Main orchestrator that coordinates all phases.

```bash
# Run all phases:
python model_migration/migrate_phased.py --product data_warehouse

# Run specific phase:
python model_migration/migrate_phased.py --product data_warehouse --phase 2

# Resume from last failure:
python model_migration/migrate_phased.py --product data_warehouse --resume

# Check status:
python model_migration/migrate_phased.py --product data_warehouse --status

# Reset all phases:
python model_migration/migrate_phased.py --product data_warehouse --reset
```

## Phases

### Phase 1: Prepare Structure
- Creates products/{product}/backend/ directories
- Creates AppConfig (apps.py)
- Creates __init__.py files
- **Manual step**: Add to INSTALLED_APPS in posthog/settings/web.py

### Phase 2: Move Files 1:1
- Executes `git mv` for each file in file_moves
- Preserves exact directory structure
- No shim removal yet

### Phase 3: Update Imports
- Runs import_rewriter.py across entire codebase
- Rewrites all imports from old to new paths
- Uses moves.yml as configuration

### Phase 4: Validate Django
- Runs `python manage.py migrate --plan`
- Ensures Django loads without errors
- Fails if any import errors or model issues

### Phase 5: Generate Django Migrations
- Runs `python manage.py makemigrations {product}`
- Creates migration files for ContentType updates
- Adds db_table declarations if needed

## Phase Tracker

State is tracked in `phase_tracker.yml`:

```yaml
product: data_warehouse
status: in_progress
current_phase: 2
phases:
  - id: 1
    name: prepare_structure
    status: completed
    timestamp: '2025-10-27T17:19:35.126292'
  - id: 2
    name: move_files
    status: pending
  # ...
```

**Status values:**
- `pending`: Not yet started
- `in_progress`: Currently executing
- `completed`: Successfully finished
- `failed`: Encountered error (stores error message)

## Usage Workflow

### Initial Setup (One-time)

```bash
# 1. Generate moves.yml
python model_migration/move_scanner.py --product data_warehouse

# 2. Review moves.yml (verify paths are correct)
cat model_migration/moves.yml
```

### Running Migration

```bash
# Run all phases (stops on error):
python model_migration/migrate_phased.py --product data_warehouse

# If phase fails, fix the tool and resume:
python model_migration/migrate_phased.py --product data_warehouse --resume

# Check current status anytime:
python model_migration/migrate_phased.py --product data_warehouse --status
```

### Development/Testing

```bash
# Run single phase for testing:
python model_migration/migrate_phased.py --product data_warehouse --phase 3

# Reset to start over:
python model_migration/migrate_phased.py --product data_warehouse --reset
git reset --hard HEAD  # Reset file changes
```

## Current Limitations

### 1. Symbol Re-exports (Star Imports)

The move_scanner doesn't currently track star imports:
```python
# posthog/warehouse/models/__init__.py
from .table import *  # Not tracked
```

**Workaround**: Import rewriter handles module-level imports correctly even without symbol mapping:
```python
# This works:
from posthog.warehouse.models import DataWarehouseTable
# Becomes:
from products.data_warehouse.backend.models import DataWarehouseTable
```

**To enhance**: Parse target files to discover exported classes when star imports are found.

### 2. Django-Specific Handling

Not yet implemented:
- ForeignKey string reference updates (`"User"` → `"posthog.User"`)
- apps.get_model() calls
- Django template {% load %} tags
- Activity logging describer paths

**Workaround**: These require manual fixes or enhancements to import_rewriter.py.

### 3. INSTALLED_APPS Update

Phase 1 requires manually adding the app to PRODUCTS_APPS in posthog/settings/web.py.

**To automate**: Parse and modify Python AST to insert the app config string.

## Comparison to Old System

| Aspect | Old (migrate_models.py) | New (migrate_phased.py) |
|--------|------------------------|-------------------------|
| File movement | Inline with script | Separate phase |
| Import updates | Regex + LibCST mixed | Pure LibCST |
| State tracking | None | phase_tracker.yml |
| Resumability | No | Yes |
| Validation | At end only | After each phase |
| Debugging | Hard (monolithic) | Easy (isolated phases) |
| Manual fixes | Expected | Tool should handle |
| Shim handling | Removes immediately | Preserves in place |

## Testing on Baseline Branch

The system has been tested on the `chore/model-migrations-baseline` branch:

```bash
# Status:
✓ move_scanner.py - Generates moves.yml correctly (63 files, 9 modules)
✓ import_rewriter.py - Successfully rewrites imports
✓ phase_tracker.py - Tracks state correctly
✓ migrate_phased.py - Phase 1 completed successfully

# Not yet tested:
⏳ Phase 2 (move files) - Ready to test
⏳ Phase 3 (update imports) - Should work based on standalone tests
⏳ Phase 4 (validate) - Unknown if Django will load
⏳ Phase 5 (migrations) - Depends on phase 4 success
```

## Next Steps

### To Complete data_warehouse Migration

1. **Add to INSTALLED_APPS** (manual step from phase 1):
   ```python
   # posthog/settings/web.py
   PRODUCTS_APPS = [
       # ...
       "products.data_warehouse.backend.apps.DataWarehouseConfig",
   ]
   ```

2. **Run remaining phases**:
   ```bash
   python model_migration/migrate_phased.py --product data_warehouse --resume
   ```

3. **If phase 4 fails** (Django validation):
   - Check error in phase_tracker.yml
   - Likely: circular imports, missing models, ForeignKey issues
   - Enhance import_rewriter.py or fix manually
   - Reset and retry: `--reset` then `--resume`

4. **If phase 3 fails** (import updates):
   - Check which files failed
   - Add handling to import_rewriter.py for edge cases
   - Reset and retry

### To Enhance System

1. **Symbol re-export discovery**:
   - Parse Python files to extract exported classes
   - Handle star imports by discovering actual symbols
   - Update move_scanner.py

2. **Django-specific handlers**:
   - ForeignKey string reference transformer
   - apps.get_model() call rewriter
   - Add to import_rewriter.py

3. **Automated INSTALLED_APPS**:
   - AST-based Python file modification
   - Add to phase 1

4. **Integration tests**:
   - Test on small product first (not data_warehouse)
   - Verify end-to-end flow
   - Document common failure modes

## Files Changed

On baseline branch:
```
new file:   model_migration/move_scanner.py
new file:   model_migration/import_rewriter.py
new file:   model_migration/phase_tracker.py
new file:   model_migration/migrate_phased.py
new file:   model_migration/moves.yml (generated)
new file:   model_migration/phase_tracker.yml (generated)
```

## Lessons Learned

### What Worked Well
1. ✅ LibCST article provided solid foundation
2. ✅ Phase separation makes debugging much easier
3. ✅ State tracking enables incremental development
4. ✅ Declarative moves.yml is clear and reviewable

### What Needs Improvement
1. ⚠️ Symbol discovery for star imports
2. ⚠️ Django-specific edge cases
3. ⚠️ More comprehensive error messages
4. ⚠️ Validation between phases (not just at end)

### Compared to Previous Attempts
- **Previous**: Tried to do everything at once, hard to debug
- **Now**: Clean phases, easy to isolate and fix issues
- **Previous**: Manual fixes expected
- **Now**: Tool should handle it (philosophy shift)

## Committing This Work

When ready to commit to baseline branch:

```bash
git add model_migration/move_scanner.py
git add model_migration/import_rewriter.py
git add model_migration/phase_tracker.py
git add model_migration/migrate_phased.py
git add model_migration/PHASED_MIGRATION_SYSTEM.md

# DO NOT commit:
# - model_migration/moves.yml (product-specific, generated)
# - model_migration/phase_tracker.yml (runtime state)
# - Any migration output in products/

git commit -m "feat(migration): add phased migration system with import rewriter

- move_scanner.py: auto-discovers structure, generates moves.yml
- import_rewriter.py: LibCST-based import transformer (from article)
- phase_tracker.py: state tracking for idempotent execution
- migrate_phased.py: orchestrator with 5 discrete phases
- Clean separation: file moves, import updates, validation
- Phase tracking enables resume from failure
- Based on libcst.md article approach"
```
