# Migration Branch Management Workflow

## Branch Strategy

We use two types of branches for model migrations:

1. **`chore/model-migration-baseline`** - Script development branch
    - Contains migration scripts (fix_product_structure.py, migrate_models.py, remove_shims_unified.py)
    - Actively developed and adjusted as we learn
    - **Rebased on master** (not pushed, force-push safe)
    - Cannot merge to master yet (work in progress)

2. **`chore/models-migrations-<product>`** - Migration output branches
    - Contains actual migration results from running scripts
    - Used for PR review
    - **Linear history** (for clean reviews)
    - Gets stale as master moves forward

## The Problem

- Master moves fast and creates conflicts
- Migration branches get stale and need updates
- Scripts are still being adjusted
- Want to preserve PR review comments
- Want clean, linear history for final review

## Before You Start

**CRITICAL**: Work with a single master commit throughout the entire process. Do NOT pull master between steps.

```bash
# Fetch master and note the commit hash
git fetch origin master
git log origin/master --oneline -1
# Note this hash - you'll use it throughout the workflow
# Example output: afa75e90ac feat(ma): update label for conversion toggler
MASTER_HASH="afa75e90ac"  # Use your actual hash
```

Use `$MASTER_HASH` instead of `master` in all git commands below. This ensures:

- Consistent base across all branches
- No surprise conflicts from new master commits
- Reproducible process if something goes wrong

## The Hybrid Merge Workflow

This workflow keeps PR branches updated while preserving review comments and getting clean script output:

### Step 1: Merge Master into Stale Branch

```bash
git checkout chore/models-migrations-<product>
git merge $MASTER_HASH
# Fix conflicts (don't spend too much time - they'll be overridden anyway)
# Just get it compiling/working
git add .
git commit -m "Merge master"
```

**Why**: Incorporates all master changes, though conflict resolution might be messy.

### Step 2: Create Fresh Branch with Soft Reset Technique

**Problem**: We need model_migration/ folder from baseline but want master's commit history.

**Solution**: Create from baseline, then immediately soft reset to master.

```bash
# Create fresh branch from baseline (to get model_migration/ folder)
git checkout chore/model-migrations-baseline
git checkout -b chore/models-migrations-<product>-fresh

# CRITICAL: Immediately soft reset to master commit
# This keeps the model_migration/ folder in working tree but resets history to master
git reset --soft $MASTER_HASH

# Now working tree has:
# - model_migration/ folder (from baseline)
# - All other files at master state
# - Commit history is clean master history

# Run the migration script (will pause for review)
python model_migration/migrate_models.py --single

# Script will pause after file moves and import updates
# IMPORTANT: Review the changes carefully:
# 1. Check git status and git diff
# 2. Verify import transformations are correct
# 3. Fix any issues (see "Common Obstacles" section below)

# When script pauses, test the migration plan
python manage.py migrate --plan

# If all looks good, continue the script to generate Django migrations
python model_migration/migrate_models.py --single --continue

# Script will generate migrations and display them
# Review the generated migration files carefully

# Commit ONLY the migration output (exclude model_migration/)
git add -A ':(exclude)model_migration/'
git commit -m "chore(models): migrate <product> models to products app"
```

**Why**:

- Soft reset gives us clean master history without baseline commits
- We still have model_migration/ folder in working tree to run scripts
- Excluding model_migration/ from commit keeps script development separate
- The `--single` flag processes one migration at a time with review checkpoints

**Important**: If you made changes to migration scripts during this process, save them:

```bash
# Save script changes to temp files (if you modified them)
cp model_migration/migrate_models.py /tmp/migrate_models.py.backup
cp model_migration/WORKFLOW.md /tmp/WORKFLOW.md.backup
cp model_migration/migration_config.json /tmp/migration_config.json.backup

# Later, apply script changes to baseline branch
git checkout chore/model-migrations-baseline
cp /tmp/migrate_models.py.backup model_migration/migrate_models.py
cp /tmp/WORKFLOW.md.backup model_migration/WORKFLOW.md
cp /tmp/migration_config.json.backup model_migration/migration_config.json
git add model_migration/
git commit -m "feat(migration-scripts): [describe script improvements]"
```

### Step 2.5: Move API and Query Runner Files (Manual Step)

After the migration script completes, manually move product-specific files from shared locations to the product's backend:

#### A. Move API Files

```bash
# Check if product has API files in posthog/api/
ls posthog/api/<product>.py posthog/api/test/test_<product>.py 2>/dev/null

# If they exist, create API structure
mkdir -p products/<product>/backend/api/test
touch products/<product>/backend/api/__init__.py

# Move files
git mv posthog/api/<product>.py products/<product>/backend/api/<product>.py
git mv posthog/api/test/test_<product>.py products/<product>/backend/api/test/test_<product>.py

# Update imports in the moved API file
# Models should already use new paths from script
# Update any other internal imports

# Find and update files that import from posthog.api.<product>
rg "from posthog.api.<product> import" --type py
# Update each file to import from products.<product>.backend.api.<product>

# Optional: Add backward-compatible re-exports if needed
# In products/<product>/backend/api/__init__.py:
# from .product import *  # Re-export everything

# Test the changes
pytest products/<product>/backend/api/test/
```

#### B. Move HogQL Query Runners

```bash
# Check if product has query runners in posthog/hogql_queries/
ls posthog/hogql_queries/<product>_*query_runner.py 2>/dev/null

# If they exist, create hogql_queries structure
mkdir -p products/<product>/backend/hogql_queries
touch products/<product>/backend/hogql_queries/__init__.py

# Move query runner files
git mv posthog/hogql_queries/<product>_*query_runner.py products/<product>/backend/hogql_queries/

# Move related test files if they exist
git mv posthog/hogql_queries/test/test_<product>_*query_runner.py products/<product>/backend/hogql_queries/test/ 2>/dev/null || true

# Update imports in the moved query runners
# Find files that import from posthog.hogql_queries.<product>
rg "from posthog.hogql_queries.<product>" --type py
# Update each file to import from products.<product>.backend.hogql_queries

# Test the changes
pytest products/<product>/backend/hogql_queries/
```

#### C. Files that should NOT be moved

Leave these in shared locations:

- **HogQL schema definitions**: `posthog/hogql/database/schema/<product>_*.py`
  - These define ClickHouse table schemas - shared infrastructure
  - Used by the HogQL query engine across products
- **Email templates**: `posthog/templates/email/<product>_*.html`
  - Centralized template system
  - May move in future but not part of this migration

**Why manual?**

- API files are complex (ViewSets, serializers, routing)
- Import patterns vary (some use `from posthog.api.X import`, others use relative imports)
- LibCST script already has edge cases with imports
- Only 2-3 files typically, easy to do by hand
- Can verify each change incrementally

**Example products**:

API files:

- ✅ llm_analytics: Already has `products/llm_analytics/backend/api/`
- ✅ messaging: Already has `products/messaging/backend/api/`
- ✅ data_warehouse: Already has `products/data_warehouse/backend/api/`
- ❌ error_tracking: Still has `posthog/api/error_tracking.py` (needs manual move)
- ❌ surveys: Still has `posthog/api/survey.py` (future work)

HogQL query runners:

- ✅ marketing_analytics: Already has `products/marketing_analytics/backend/hogql_queries/`
- ✅ revenue_analytics: Already has `products/revenue_analytics/backend/hogql_queries/`
- ✅ logs: Already has `products/logs/backend/*_query_runner.py`
- ❌ error*tracking: Still has `posthog/hogql_queries/error_tracking*\*query_runner.py` (needs manual move)

**Commit this separately**:

```bash
git add products/<product>/backend/api/
git commit -m "chore(<product>): move API files to products backend"
```

### Step 3: Merge Fresh Work Back into Review Branch

```bash
git checkout chore/models-migrations-<product>
git merge chore/models-migrations-<product>-fresh
# Review merge carefully - do NOT blindly accept all changes
# The script may have bugs that accidentally removed code
# Manually resolve conflicts, preferring fresh for migration changes

# CRITICAL: Validate no code was accidentally removed by the script
git diff HEAD~1 HEAD --stat | sort -k2 -n -r | head -20
# Look for files with large negative line counts (unexpected deletions)
# Investigate any files with >50 lines deleted

# Check specific critical files that often have issues:
git diff HEAD~1 HEAD -- posthog/tasks/email.py posthog/conftest.py
# Make sure no functions were accidentally removed

# CRITICAL: Amend the merge commit to remove model_migration/ folder
# (soft reset may have included it in merge)
git rm -r model_migration/ 2>/dev/null || true
git commit --amend --no-edit

# Also check for accidentally committed files
git status
# If you see unwanted files, remove them:
git rm <unwanted_file>
git commit --amend --no-edit
```

**Why**:

- Corrects any messy conflict resolutions from step 1 with clean script output
- Amending removes model_migration/ folder which should only be on baseline
- Keeps PR branch clean with only migration output

### Step 4: Push to PR

```bash
git push origin chore/models-migrations-<product> --force-with-lease
```

**Why**:

- Same branch = preserves PR and all review comments
- --force-with-lease protects against accidentally overwriting others' work

## Common Obstacles

### App Config Naming Bug

**Symptom**: `ImportError: Module 'products.<product>.backend.apps' does not contain a 'Error_TrackingConfig' class`

**Cause**: Script uses `.title()` which creates `Error_TrackingConfig` instead of `ErrorTrackingConfig`

**Fix**: Manually edit `posthog/settings/web.py`:

```python
# Wrong:
"products.error_tracking.backend.apps.Error_TrackingConfig",
# Right:
"products.error_tracking.backend.apps.ErrorTrackingConfig",
```

### ForeignKey Cross-App References

**Symptom**: `(fields.E300) Field defines a relation with model 'User', which is either not installed, or is abstract`

**Cause**: Multi-line ForeignKey definitions don't match regex, or wrong app label

**Fix**: Manually update models.py with proper app labels:

```python
# Wrong:
models.ForeignKey("User", ...)
# Right:
models.ForeignKey("posthog.User", ...)

# Wrong (Role is in ee app, not posthog):
models.ForeignKey("posthog.Role", ...)
# Right:
models.ForeignKey("ee.Role", ...)
```

### Migration Numbering Conflicts

**Symptom**: Your migration number (e.g. 0877) conflicts with new migrations in master

**Cause**: Master moved forward after you noted $MASTER_HASH

**Fix**: Before generating migrations, check current max:

```bash
cat posthog/migrations/max_migration.txt
# If it's higher than expected, you may need to renumber
```

### Accidentally Committed Files

**Symptom**: `git status` shows files like `compare_ci_jobs.py` or other unrelated files

**Fix**: Remove them and amend:

```bash
git rm <unwanted_file>
git commit --amend --no-edit
```

### LibCST Script Bugs

**Symptom**: Functions or code blocks completely missing after migration, CI failures with import errors

**Cause**: LibCST can accidentally remove code when transforming imports, especially:

- Multi-line imports
- Code added to master after baseline branch was created
- Complex import patterns
- Files with multiple imports from the same module

**Example**: During error_tracking migration:

- `send_discussions_mentioned` function was removed from `posthog/tasks/email.py` (48 lines)
- `DISCUSSIONS_MENTIONED` enum value and related code deleted
- `pytest_sessionstart` fixture removed from `posthog/conftest.py`

**Prevention**:

1. Carefully review ALL modified files after script runs during pause
2. Check for large deletions: `git diff --stat`
3. Compare line counts before/after: `wc -l file.py`
4. Test critical imports manually:

    ```bash
    python -c "from posthog.tasks.email import send_discussions_mentioned"
    python -c "from posthog.conftest import pytest_sessionstart"
    ```

5. Run tests locally before pushing

**Fix**: Restore affected files from master and manually apply import changes:

```bash
# Restore the file from master
git checkout origin/master -- posthog/tasks/email.py

# Then manually update ONLY the import line
# OLD:
from posthog.models.error_tracking import ErrorTrackingIssueAssignment
# NEW:
from products.error_tracking.backend.models import ErrorTrackingIssueAssignment
```

**Why this happens**: The LibCST script uses regex and AST transformations that can have edge cases. Always validate its output manually.

## If Things Go Wrong

### Reset PR Branch and Start Over

If you messed up and want to start clean:

```bash
# Find the commit before you started (e.g., before "Merge master" commit)
git log --oneline -20
# Note the commit hash before your work

# Hard reset to that commit
git checkout chore/models-migrations-<product>
git reset --hard <commit-before-your-work>

# Now follow the workflow again from Step 1
```

### Amend Multiple Times if Needed

Don't worry about amending the merge commit multiple times to get it right:

```bash
# Check authorship before amending
git log -1 --format='%an %ae'
# Make sure it's your commit

# Check branch is ahead (not pushed yet or safe to force push)
git status

# Amend as many times as needed
git rm <file>
git commit --amend --no-edit
```

## Why This Works

✅ **Preserves PR and review comments** - Same branch, same PR number
✅ **Gets clean script output** - Fresh branch has correct generated code
✅ **No baseline commits in history** - Soft reset technique keeps history clean
✅ **Incorporates master changes** - Both merges bring in latest master
✅ **Conflicts resolved by scripts** - Fresh branch overrides manual conflict resolution from step 1

The key insight: Step 3 merge **corrects** the potentially messy step 1 merge by applying clean script output.

## Conflict Resolution Strategy

### Step 1 Conflicts (master → stale)

- Don't spend too much time making these perfect
- Just get it working
- These resolutions will be overridden anyway

### Step 3 Conflicts (fresh → stale)

**IMPORTANT**: Do NOT use `-X theirs` blindly - the fresh branch may have script bugs!

- **Carefully review each conflict** before resolving
- For migration-related files (models, migrations, app configs):
  - Generally prefer the fresh branch version
  - But validate no code was accidentally deleted
- For unrelated files:
  - Keep master changes if they don't conflict with migration
- **Always validate** after merge:

    ```bash
    # Check for unexpected deletions
    git diff HEAD~1 HEAD --stat
    # Review critical files manually
    git diff HEAD~1 HEAD -- posthog/tasks/email.py posthog/conftest.py
    ```

- If in doubt, manually checkout fresh version and inspect:

    ```bash
    git checkout --theirs path/to/file.py
    git diff HEAD -- path/to/file.py  # Review what changed
    ```

## Alternative Workflows (Not Recommended Currently)

### Option A: Recreate Branches

- Good while scripts are in flux
- Fast and clean
- Loses review comments

### Option B: Just Merge Master

- Simplest approach
- Non-linear history
- Manual conflict resolution

### Option C: Merge + Final Rebase

- Incremental conflicts during work
- Clean up with rebase before final review
- More complex

## When to Use Which Strategy

- **While scripts are changing**: Use hybrid workflow (documented above)
- **Once scripts are stable**: Consider switching to simple merge workflow
- **For very large migrations**: Consider breaking into smaller PRs per product

## Cleanup

After PR is merged, clean up temporary branches:

```bash
git branch -D chore/models-migrations-<product>-fresh
```
