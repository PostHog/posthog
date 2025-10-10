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

## The Hybrid Merge Workflow

This workflow keeps PR branches updated while preserving review comments and getting clean script output:

### Step 1: Merge Master into Stale Branch

```bash
git checkout chore/models-migrations-error-tracking
git merge master
# Fix conflicts (don't spend too much time - they'll be overridden anyway)
# Just get it compiling/working
git add .
git commit -m "Merge master"
```

**Why**: Incorporates all master changes, though conflict resolution might be messy.

### Step 2: Create Fresh Branch and Run Scripts

```bash
git checkout master
git pull
git checkout -b chore/models-migrations-error-tracking-fresh

# Run the migration scripts
python model_migration/fix_product_structure.py
python model_migration/migrate_models.py error_tracking
python model_migration/remove_shims_unified.py

git add -A
git commit -m "Fresh migration from scripts"
```

**Why**: Gets clean, correct output from latest scripts on latest master.

### Step 3: Merge Fresh Work Back into Review Branch

```bash
git checkout chore/models-migrations-error-tracking
git merge chore/models-migrations-error-tracking-fresh

# For conflicts: prefer the fresh branch version
# Option A: Auto-prefer fresh branch
git merge chore/models-migrations-error-tracking-fresh -X theirs

# Option B: Manual selection for migrated files
git checkout --theirs products/error_tracking/backend/
git add products/error_tracking/backend/
```

**Why**: Corrects any messy conflict resolutions from step 1 with clean script output.

### Step 4: Push to PR

```bash
git push origin chore/models-migrations-error-tracking
```

**Why**: Same branch = preserves PR and all review comments!

## Why This Works

✅ **Preserves PR and review comments** - Same branch, same PR number
✅ **Gets clean script output** - Fresh branch has correct generated code
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

## Gotchas to Watch Out For

⚠️ **History is non-linear** - You'll have 2 merge commits, but that's fine
⚠️ **Don't skip step 1** - Need master changes first
⚠️ **Step 3 is critical** - This is where clean output wins

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
git branch -D chore/models-migrations-error-tracking-fresh
```
