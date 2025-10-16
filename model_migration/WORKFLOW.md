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

# CRITICAL: Configure migration_config.json BEFORE running script
# Set ONLY your target product to "todo", all others to "skip"
cat > model_migration/migration_config.json <<EOF
{
    "migrations": [
        {
            "name": "error_tracking",
            "status": "todo",
            "models": ["ErrorTrackingIssue", "ErrorTrackingGroup", ...]
        },
        {
            "name": "experiments",
            "status": "skip"
        }
    ]
}
EOF

# Run the migration script (will pause for review)
python model_migration/migrate_models.py --single

# Script will pause after file moves and import updates
# IMPORTANT: Review the changes carefully:
# 1. Check git status and git diff
# 2. Verify import transformations are correct
# 3. Fix any issues (see "Common Obstacles" section below)
# 4. DO NOT commit yet - manual fixes needed first

# Fix known issues (see "Common Script Pitfalls" section):
# - App config naming (Error_TrackingConfig → ErrorTrackingConfig)
# - ForeignKey cross-app references ("posthog.Role" → "ee.Role")
# - Any stale imports script missed

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

## Key Learnings and Pitfalls

### Validation is Critical

Always validate migrations by running them from scratch before final merge:

1. **Start Fresh from Latest Master**
    - Pick latest master commit hash
    - Create fresh branch from baseline with soft reset technique
    - Run entire migration workflow from scratch
    - This catches script bugs, missing manual fixes, stale logic

2. **Compare Fresh vs PR Branch**
    - Use git diff to compare branches
    - Isolate master merge issues from migration issues
    - Confirms original work was done correctly

3. **Test Migrations Actually Work**
    - Run `python manage.py migrate --plan`
    - Apply migrations to database
    - Verify ContentType updates with SQL queries
    - Create test migration in new app location to prove it works
    - **CRITICAL**: Revert any test migrations before committing (fields, migration files)
    - Only commit actual migration work, never testing artifacts

### Replacement Merge Strategy

When you need to completely replace PR branch with fresh validated output:

```bash
# Checkout PR branch
git checkout chore/models-migrations-<product>

# Start merge but use "ours" strategy (keeps PR branch history)
git merge -s ours --no-commit chore/models-migrations-<product>-fresh

# Replace entire tree with fresh branch content
git read-tree -u --reset chore/models-migrations-<product>-fresh

# CRITICAL: Remove model_migration/ folder before committing
git rm -rf model_migration/ 2>/dev/null || true

# Commit the merge
git commit -m "merge: adopt fresh migration validation branch"
```

**Why this works**:

- Creates merge commit (preserves git history)
- Tree is identical to fresh branch (complete replacement)
- Safer than force push - can be reverted
- Preserves PR and review comments

**When to use**:

- Fresh validation reveals issues in original PR
- Want to be 100% certain output is correct
- Need to replace everything to be safe
- Don't want to manually cherry-pick fixes

### Configuration Options for Special Cases

The migration script supports several configuration options in `migration_spec` for handling non-standard model locations:

#### source_base_path

For models in non-standard locations (not `posthog/models/`):

```json
{
    "name": "data_warehouse",
    "source_base_path": "posthog/warehouse/models",
    "source_files": ["external_data_source.py", "table.py"],
    "status": "todo"
}
```

**Why**: Data warehouse models live in `posthog/warehouse/models/` instead of `posthog/models/`. Script detects this and searches the correct directory for source files.

#### model_names (for no-merge mode with continue)

When using `no-merge-models: true` with `--continue` flag, include pre-computed model names:

```json
{
    "name": "data_warehouse",
    "no-merge-models": true,
    "model_names": ["ExternalDataSource", "DataWarehouseTable", "DataWarehouseJoin"],
    "status": "todo"
}
```

**Why**: In continue mode, the script needs to identify model classes to update their db_table declarations. When source files no longer exist (already moved in first phase), it can't use AST parsing. The `model_names` array provides a pre-computed fallback, especially useful for models with complex inheritance patterns (e.g., warehouse models using ModelActivityMixin, CreatedMetaFields, etc.).

#### no-merge-models

Preserve 1:1 file structure instead of combining models:

```json
{
    "name": "data_warehouse",
    "no-merge-models": true,
    "source_files": ["external_data_source.py", "table.py"],
    "status": "todo"
}
```

**Why**: By default, script combines all source files into a single `models.py`. Use `no-merge-models: true` to create individual model files (e.g., `external_data_source.py`, `table.py`).

**CRITICAL**: When using no-merge mode:

1. Always run with `--single` flag first to move files and update imports
2. Review changes before continuing
3. Configure `model_names` in the config entry before running `--continue`
4. Script will use these names to add db_table declarations in continue mode

### Common Script Pitfalls

1. **LibCST Timeout During Cleanup**
    - Script may timeout after 2 minutes during validation/cleanup step
    - All migration work is usually complete before timeout
    - Can safely continue if files were moved and migrations generated
    - Check what got committed before timeout interrupted

2. **App Config Naming Bug**
    - Script uses `.title()` which creates `Error_TrackingConfig`
    - Always manually fix to proper PascalCase: `ErrorTrackingConfig`
    - Known issue, must be fixed every time

3. **ForeignKey Cross-App References**
    - Script doesn't detect which app a model belongs to
    - `ForeignKey("User")` should be `"posthog.User"`
    - `ForeignKey("Role")` should be `"ee.Role"` (not posthog)
    - Check all ForeignKey definitions after script runs

4. **Stale Imports**
    - API imports may not be updated (`posthog.api.X` → `products.X.backend.api.X`)
    - Remote config imports need manual fixing
    - Query runner imports need manual fixing
    - grep for old import paths after migration

5. **Test Snapshots**
    - API test snapshots contain import paths
    - Update snapshot files to reference new paths
    - Check `__snapshots__/*.ambr` files

6. **posthog/models/**init**.py Cleanup**
    - Must manually remove exported model names
    - Script doesn't clean this up automatically

7. **tach.toml Updates**
    - Add new product to posthog dependencies
    - Create new module definition for product
    - Script doesn't handle this

8. **CASCADE Fix for Tests**
    - When models reference each other across apps, tests need CASCADE
    - Add to `NonAtomicBaseTest._fixture_teardown()` in `posthog/test/base.py`
    - Use `allow_cascade=True` in flush command
    - Required for PostgreSQL FK constraints

### Testing Strategy

After migration, verify everything works:

```bash
# Run migration plan (doesn't execute)
python manage.py migrate --plan

# Check migrations applied
python manage.py showmigrations | rg error_tracking

# Verify ContentType updates in database
psql -d posthog -c "SELECT app_label, model FROM django_content_type WHERE model LIKE 'errortracking%' ORDER BY model;"

# OPTIONAL: Create test migration to prove new app location works
# This is for validation only - DO NOT COMMIT these changes

# 1. Add test field to model
echo "test_migration_field = models.CharField(max_length=100, null=True)" >> products/<product>/backend/models.py

# 2. Create and run migration
python manage.py makemigrations <product>
python manage.py migrate <product>

# 3. Verify field exists
psql -d posthog -c "\d posthog_<modelname>;" | rg test_migration

# 4. CRITICAL: Revert all test changes before committing
git checkout products/<product>/backend/models.py
git clean -fd products/<product>/backend/migrations/
# Restore max_migration.txt if you modified it
git checkout products/<product>/backend/migrations/max_migration.txt

# Run product tests
pytest products/<product>/backend/

# Check for stale imports
rg "from posthog.models.<product>" --type py
rg "from posthog.api.<product>" --type py
```

**IMPORTANT**: Test migrations are for validation only. Never commit:

- Test fields added to models
- Test migration files (000X*test*\*.py)
- Modified max_migration.txt from testing

Always revert these before committing.

### Manual File Organization

After script runs, manually organize product-specific files:

1. **API files**: `posthog/api/X.py` → `products/X/backend/api/X.py`
2. **HogQL query runners**: `posthog/hogql_queries/X_*.py` → `products/X/backend/hogql_queries/`
3. **Test files**: Move with their corresponding modules
4. **Update all imports** in moved files and files that import them

Leave these in shared locations:

- HogQL schema definitions (`posthog/hogql/database/schema/`)
- Email templates (`posthog/templates/email/`)

### Common Mistakes to Avoid

Based on real issues encountered:

1. **Running Wrong Product Migration**
    - ❌ Don't assume config is correct - always verify migration_config.json
    - ✅ Explicitly set target product to "todo", all others to "skip"
    - ✅ Check config before running script

2. **Committing Test Artifacts**
    - ❌ Don't commit test migration files (000X*test*\*.py)
    - ❌ Don't commit test fields added to models
    - ✅ Always revert test changes before committing
    - ✅ Use `git status` to verify no test artifacts staged

3. **Including model_migration/ in Commits**
    - ❌ Don't commit model_migration/ folder to product branches
    - ✅ Use `git add -A ':(exclude)model_migration/'` when committing
    - ✅ Verify with `git status` after adding files
    - ✅ Remove with `git rm -rf model_migration/` if accidentally staged

4. **Blindly Accepting Merge Conflicts**
    - ❌ Don't use `-X theirs` blindly - script may have bugs
    - ❌ Don't assume fresh branch is always correct
    - ✅ Review each conflict carefully
    - ✅ Check for accidentally deleted code
    - ✅ Validate merge result with `git diff --stat`

5. **Forgetting Manual Fixes**
    - ❌ Don't assume script output is complete
    - ✅ Always check for known issues after script runs
    - ✅ Follow debugging checklist below
    - ✅ Test imports and migrations before committing

6. **Pushing Too Early**
    - ❌ Don't push until validation is complete
    - ✅ Validate locally first (migrations, tests, imports)
    - ✅ Use `--force-with-lease` when force pushing
    - ✅ Coordinate with team if branch is shared

### Baseline Branch Maintenance

Keep the baseline branch clean and rebasing-friendly with linear history:

#### Applying Script Improvements

When you improve the migration script during a run:

1. **Don't create merge commits** - Apply changes directly to baseline files
2. **Make surgical edits** - Only change what's needed for the improvement
3. **Commit individually** - Create one clean commit per logical improvement
4. **Example**:

    ```bash
    # Make targeted edits to baseline files
    # Edit model_migration/migrate_models.py to fix a bug
    # Edit model_migration/migration_config.json to add model_names

    # Stage only the improvements
    git add model_migration/migrate_models.py model_migration/migration_config.json

    # Commit with clear message
    git commit -m "feat(migration): add model_names config support for continue mode"
    ```

**Why**: Linear history keeps baseline rebasing-safe. Merge commits complicate future rebases when baseline is refreshed against master.

#### Fresh Baseline for New Runs

Before starting a new migration run:

1. Clean any leftover migration output:

    ```bash
    git checkout chore/model-migrations-baseline
    rm -rf products/<product>/backend/
    git status  # Should show clean working tree
    ```

2. Create fresh branch for the migration run:

    ```bash
    git checkout -b chore/models-migrations-<product>-fresh
    git reset --soft $MASTER_HASH
    # Configure migration_config.json for target product
    # Run migration script
    ```

3. Don't keep accumulated migration files on baseline - they're only needed during the run

### Debugging Checklist

When something doesn't work:

- [ ] App config class name is PascalCase without underscores
- [ ] All ForeignKey references have proper app labels
- [ ] posthog/models/**init**.py doesn't export moved models
- [ ] All imports updated from posthog.models.X to products.X.backend.models
- [ ] All imports updated from posthog.api.X to products.X.backend.api.X
- [ ] API files moved to products/X/backend/api/
- [ ] HogQL query runners moved to products/X/backend/hogql_queries/
- [ ] Test snapshot paths updated
- [ ] tach.toml includes new product module
- [ ] CASCADE fix added to test base class if needed
- [ ] No stale import references left in codebase
- [ ] Migrations have correct dependencies
- [ ] ContentType updates in both migrations (remove from posthog, add to new app)

## Cleanup

After PR is merged, clean up temporary branches:

```bash
git branch -D chore/models-migrations-<product>-fresh
```
