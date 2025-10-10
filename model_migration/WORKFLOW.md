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

### Step 3: Merge Fresh Work Back into Review Branch

```bash
git checkout chore/models-migrations-<product>
git merge chore/models-migrations-<product>-fresh -X theirs

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

- **Always prefer the fresh branch version** when in doubt
- Use `-X theirs` strategy for auto-resolution
- Or manually checkout fresh version for migrated files

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
