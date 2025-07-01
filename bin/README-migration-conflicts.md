# Migration Conflict Resolution

This directory contains tools to help resolve Django migration conflicts that occur when multiple developers create migrations in parallel branches.

## The Problem

When you have a PR with migrations and someone else merges migrations to master, you get conflicts because:

1. **File naming conflicts**: Both branches might have migrations numbered `0784_`, `0785_`, etc.
2. **Dependency conflicts**: Your migrations point to the wrong previous migration
3. **max_migration.txt conflicts**: Both branches update this file differently

GitHub's conflict resolution UI can't handle this automatically because it requires:
- Renaming migration files
- Updating migration dependencies in the code
- Updating `max_migration.txt` with the correct final migration name

## The Solution

### 1. Local Script (Manual)

Use the `fix-migration-conflicts.py` script locally:

```bash
# Preview what changes would be made
cd posthog
python bin/fix-migration-conflicts.py --preview

# Apply the fixes
python bin/fix-migration-conflicts.py --fix

# Check only specific app (e.g., posthog, billing)
python bin/fix-migration-conflicts.py --app posthog --preview
python bin/fix-migration-conflicts.py --app posthog --fix
```

**What it does:**
- Compares your branch with `origin/master`
- Detects migration number conflicts
- Renames your migration files to use the next available numbers
- Updates migration dependencies in the code
- Updates `max_migration.txt` files
- Creates backups before making changes

### 2. GitHub Actions (Maximum Convenience)

Use the GitHub Actions workflows for the ultimate convenient experience - complete review and approval through GitHub UI:

#### Automatic Detection (Recommended)
**The easiest way** - conflicts are detected automatically on every push:

1. **Push your code** to any branch with migrations
2. **Auto-detection runs** and checks for `max_migration.txt` conflicts  
3. **If conflicts found**, a comment is automatically posted to your PR
4. **Click "Apply Fixes"** in the comment → Type "YES" → Done!

This happens completely automatically - no manual workflow triggering needed!

#### Manual Workflows (Optional)
If you need more control or auto-detection didn't work:

**Step 1: Preview Changes**
1. Go to your PR on GitHub
2. Click the "Actions" tab  
3. Find "Migration Conflicts - Preview" workflow
4. Click "Run workflow", select your branch
5. Optionally set `app_filter` (e.g., "posthog") to check specific app only
6. Check your PR comments for a detailed preview of what will be fixed

**Step 2: Apply Changes (After Review)**
1. If the preview looks good, click the "▶️ Apply Migration Fixes" button in the PR comment
2. This opens the "Migration Conflicts - Apply Fixes" workflow  
3. Select your branch and set the same `app_filter` if you used one
4. **Type "YES"** in the confirmation field
5. Click "Run workflow" to automatically apply and commit the fixes

**What it does:**
- **Auto-detection workflow**: Automatically detects conflicts on push and posts PR comments
- **Preview workflow**: Shows exactly what changes will be made in a PR comment  
- **Apply workflow**: Applies the fixes and commits them to your branch automatically
- **Full GitHub UI**: No local commands needed, everything through browser
- **Safety**: Requires explicit "YES" confirmation before making changes
- **Smart comments**: Updates your PR with detailed results and next steps

## Example Scenario

**Before (conflict):**
```
Master branch:
├── 0782_remove_segment_hidden_destinations.py
├── 0783_remove_segment_engage_destinations.py  # ← New on master
└── max_migration.txt: "0783_remove_segment_engage_destinations"

Your branch:
├── 0782_remove_segment_hidden_destinations.py
├── 0783_add_new_feature.py                     # ← Your migration (conflicts!)
└── max_migration.txt: "0783_add_new_feature"
```

**After (resolved):**
```
Your branch:
├── 0782_remove_segment_hidden_destinations.py
├── 0783_remove_segment_engage_destinations.py  # ← From master  
├── 0784_add_new_feature.py                     # ← Renumbered
└── max_migration.txt: "0784_add_new_feature"   # ← Updated
```

The script also updates any dependencies in `0784_add_new_feature.py` to point to the correct previous migration.

## Usage Tips

1. **GitHub UI First**: Use the GitHub Actions workflows for maximum convenience
2. **Always preview**: The preview workflow shows exactly what will change before you commit
3. **Review carefully**: Check the PR comment preview before clicking "Apply"
4. **Use app filters**: For complex changes, use `app_filter` to fix one app at a time
5. **Test locally**: After fixes are applied, test your migrations locally to ensure they work
6. **Local fallback**: Use the local script if you prefer command-line or need to troubleshoot

## Safety Features

- **Backups**: Creates temporary backups before making changes
- **Error recovery**: Restores backups if something goes wrong
- **Preview mode**: See exactly what will change before applying
- **Git integration**: Works with your current git branch and respects `.gitignore`

## Supported Apps

Currently configured for:
- `posthog/posthog` (main app)
- `billing/billing`
- `ee` (enterprise edition)
- `products/early_access_features`
- `products/user_interviews`

To add more apps, edit the `apps_with_migrations` list in `fix-migration-conflicts.py`.

## Troubleshooting

**Script fails with git errors:**
- Ensure you're in a git repository
- Check that `origin/master` exists: `git fetch origin master`
- Ensure you have the latest changes: `git fetch --all`

**Dependencies not updated correctly:**
- Check that your migration files have the standard Django format
- Ensure dependencies are formatted like `("app_name", "0123_migration_name")`

**GitHub Actions fails:**
- Ensure the workflow files are in `posthog/.github/workflows/`
- Check that you have permissions to run workflows on the repository
- Verify that the branch is pushed to the remote repository

## Advanced Usage

**Custom git remote:**
If your remote isn't called `origin`, edit the script and replace `origin/master` with your remote name.

**Different base branch:**
If you're not branching from `master`, edit the script to use your base branch name.

**Complex dependency chains:**
The script handles migration dependencies within the same app, but cross-app dependencies may need manual review. 