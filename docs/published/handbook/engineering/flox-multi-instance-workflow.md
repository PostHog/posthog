---
title: Isolated Development with Flox
showTitle: true
noindex: true
---

This guide explains how to create isolated PostHog development environments using Flox and Git worktrees for seamless branch switching.

**Key Benefits:**

- Work on multiple branches simultaneously with isolated environments
- Each worktree has its own Flox environment and Python dependencies
- Quick switching between features, bug fixes, and PR reviews
- Standard `bin/start` command works in each worktree

> [!IMPORTANT]
> **Important:** Only one PostHog instance (`bin/start`) can run at a time since they all use the same ports. The workflow focuses on quickly stopping one instance and starting another.

## Prerequisites

1. **Flox installed**: https://flox.dev/docs/install-flox/
2. **Git worktrees support** (Git 2.5+)
3. **GitHub CLI** (for PR checkout): `brew install gh`
4. **jq** (for PR JSON parsing): `brew install jq`
5. **direnv** (recommended): `brew install direnv`

## Configuration

### Worktree Location

By default, worktrees are created in `~/.worktrees/posthog/`. You can customize this location by setting the `POSTHOG_WORKTREE_BASE` environment variable:

```bash
# In your shell profile (~/.zshrc or ~/.bashrc)
export POSTHOG_WORKTREE_BASE="/path/to/your/preferred/location"
```

For example:

```bash
export POSTHOG_WORKTREE_BASE="$HOME/code/worktrees"
# Worktrees will be created in ~/code/worktrees/<branch-name>
```

### Worktree Location Management

The `phw list` and `phw remove` commands work with **all** your PostHog worktrees, regardless of where they were created. This is helpful if you:

- Changed your `POSTHOG_WORKTREE_BASE` setting after creating some worktrees
- Have worktrees in multiple locations
- Want to clean up old worktrees from previous setups

**Example scenario:**

```bash
# You had worktrees in the old location
ls ~/.worktrees/posthog/
# old-feature/  pr-1234-teammate/

# You changed your worktree base
export POSTHOG_WORKTREE_BASE="$HOME/dev/worktrees"

# phw list still shows ALL worktrees
phw list
# Shows both old location worktrees AND new location worktrees

# phw remove works with any worktree location
phw remove pr-1234-teammate  # Works even though it's in old location!
```

This uses Git's native worktree tracking (`git worktree list`) rather than trying to guess paths.

## Quick Start

### 1. One-Time Setup

In all these examples, replace `~/dev/posthog/posthog` with your local path to the PostHog repo.

```bash
# Install dependencies
brew install direnv gh jq

# Add direnv hook to your shell (~/.zshrc or ~/.bashrc)
eval "$(direnv hook zsh)"  # or bash

# Add the phw function for auto-cd functionality
echo 'source ~/dev/posthog/posthog/bin/phw' >> ~/.zshrc  # or ~/.bashrc

# Reload your shell
source ~/.zshrc  # or ~/.bashrc

# Verify setup in main repo
cd ~/dev/posthog/posthog
flox activate
# You should see Flox environment activate and uv sync run
```

### 2. Daily Workflow with `phw`

After setup, use the `phw` command for everything:

#### Create a NEW branch

```bash
# creates branch haacked/new-feature and worktree haacked/new-feature off of master
phw create haacked/new-feature
# You're now IN the worktree with Flox activated!
bin/start
# Access at http://localhost:8000

# Or specify a different base branch
phw create haacked/new-feature master
```

#### Work on EXISTING branch

```bash
phw checkout haacked/new-feature
# Creates worktree for existing branch, Flox activated!
bin/start
# Access at http://localhost:8000
```

#### Switch to EXISTING worktree

```bash
phw switch haacked/new-feature
# Switches to already created worktree, Flox activated!
bin/start
# Access at http://localhost:8000
```

#### Review a Pull Request

```bash
phw pr 12345
# Fetched PR, switched to worktree, ready to test!
bin/start
# Access at http://localhost:8000
```

## Real-World Example

```bash
# 9:00 AM - Start working on new dashboard
phw create haacked/analytics-dashboard
bin/migrate  # Run migrations
bin/start    # Start development
# Work on feature at http://localhost:8000

# 10:30 AM - Urgent production bug!
# Stop current PostHog instance first
# Ctrl+C to stop bin/start
phw checkout master
# Already in main worktree with Flox activated
git pull origin master
bin/start    # Start development
# Fix bug, test at http://localhost:8000

# 11:00 AM - Review teammate's PR
# Stop current instance first
phw pr 5678
# Automatically fetches PR and switches to it
bin/start
# Review at http://localhost:8000

# 2:00 PM - Back to feature work
# Stop current instance and switch back
phw switch haacked/analytics-dashboard
# You may see interactive prompt - press Enter to skip nesting, or run 'exit' first
bin/start    # Continue where you left off

# 5:00 PM - Cleanup
phw list                                # See all worktrees
phw remove pr-5678-teammate            # Done with PR review
```

## Common Workflows

### Switching Between Worktrees

Since you can only run one PostHog instance at a time, the workflow focuses on quickly switching between isolated environments:

```bash
# Create isolated worktrees for different tasks
phw create haacked/feature-analytics
phw checkout bugfix/login-issue
phw pr 1234

# Work on feature
phw switch haacked/feature-analytics
bin/start  # Work on feature

# Stop and switch to bug fix
# Ctrl+C to stop
phw switch bugfix/login-issue
bin/start  # Switch to bug fix work

# Stop and switch to PR review
# Ctrl+C to stop
phw switch pr-1234-teammate
bin/start  # Review PR
```

### Managing Your Worktrees

```bash
# See all your worktrees
phw list

# Output:
# All PostHog Worktrees:
#
# Branch                        Path                                           Location
# ------                        ----                                           --------
# haacked/improved-workflow     /Users/username/dev/posthog/posthog            other
# haacked/analytics-dashboard   /Users/username/.worktrees/posthog/haacked/... current
# main                         /Users/username/.worktrees/posthog/main        current
# pr-5678-teammate             /Users/username/.worktrees/posthog/pr-5678-... current
#
# Legend:
#   current = in current worktree base (/Users/username/.worktrees/posthog)
#   other   = in different location

# Remove when done (works regardless of location)
phw remove pr-5678-teammate
```

## Quick Reference

### Commands

```bash
phw create <branch> [base-branch]   # Create new branch & worktree (defaults to master)
phw checkout <branch>               # Create worktree for existing branch
phw switch <branch>                 # Switch to existing worktree
phw pr <number>                     # Checkout PR in worktree
phw remove <branch>                 # Remove worktree
phw list                            # List all worktrees
```

### Workflow Benefits

- **Isolated environments**: Each worktree has its own Flox environment and Python dependencies
- **Quick switching**: Move between branches without losing work or rebuilding dependencies
- **Clean separation**: Different features, bug fixes, and PR reviews stay completely separate
- **Standard tools**: Uses familiar `bin/start` command in each worktree

## How It Works

1. **direnv + `.envrc`**: Automatically activates Flox when you enter any worktree directory
2. **Flox Environment**: Each worktree gets its own `.flox/env/manifest.toml` and Python venv
3. **UV Caching**: Flox's `uv sync` uses its own caching, so dependencies are efficiently shared
4. **Git Worktrees**: Each branch lives in its own directory with isolated Git state
5. **`phw` function**: Provides auto-cd functionality and smart tab completion
6. **Git-native Management**: `phw list` and `phw remove` use Git's authoritative worktree tracking, working with worktrees from any location

### The Magic Flow

```text
phw create branch → creates worktree → copies .envrc → cd to worktree →
direnv detects .envrc → activates Flox → runs uv sync → ready to code!
```

### Interactive Environment Switching

When you switch between worktrees while already in a Flox environment, you'll see an interactive prompt to prevent unexpected nested environments:

```text
⚠️  About to activate Flox environment in worktree while already in environment for:
   /Users/username/dev/posthog/posthog

Continue with nested activation? (y/N):
```

**Your options:**

- **Press Enter or 'n'** (recommended): Skips activation. Run `exit` first to cleanly switch environments
- **Type 'y'**: Proceeds with nested activation (you'll need multiple `exit` commands later)
- **Ctrl+C**: Cancels direnv entirely so you can run `exit` and retry

**Best practice:** When switching between worktrees, exit your current Flox environment first:

```bash
# Currently in main repo with Flox active
exit  # Leave current Flox environment
cd ~/.worktrees/posthog/my-branch  # Switch to worktree
# Flox activates cleanly without nesting prompt
```

## Tips and Tricks

### Tab Completion

The `phw` function includes smart tab completion:

- `phw create <TAB>` - Suggests "haacked/" prefix
- `phw checkout <TAB>` - Shows all available branches
- `phw remove <TAB>` - Shows removable worktrees

### Resource Management

```bash
# Clean up unused worktrees
git worktree prune

# See current worktrees
phw list
```

### Debugging

```bash
# Check Flox environment status
flox list

# See what's installed in current environment
flox search --installed

# Check current worktrees
git worktree list
```

## Troubleshooting

### direnv not activating

```bash
# Make sure direnv is allowed in the worktree
phw switch your-branch
direnv allow

# Check direnv is properly hooked into your shell
which direnv  # Should show /opt/homebrew/bin/direnv or similar
echo $DIRENV_DIR  # Should show something when in a direnv directory
```

### Flox activation fails

```bash
# Trust the environment
flox activate --trust

# Or reinstall Flox environment
rm -rf .flox
cp -r ~/dev/posthog/posthog/.flox/env .flox/
flox activate
```

### phw command not found

```bash
# Make sure you've sourced the phw script
source ~/dev/posthog/posthog/bin/phw

# Add it permanently to your shell profile
echo 'source ~/dev/posthog/posthog/bin/phw' >> ~/.zshrc
```

### Dependencies out of sync

```bash
# Force reinstall in Flox environment
flox activate -- uv sync --reinstall
```

### Interactive Flox prompt behavior

**Problem**: You see the interactive prompt every time you switch directories

**Solution**: This is expected behavior when switching between worktrees. Choose the best approach:

```bash
# Option 1: Skip nesting (recommended)
# Press Enter or 'n' when prompted, then:
exit  # Leave current environment
phw switch your-branch  # Switch cleanly and consistently

# Option 2: Allow nesting (if you prefer)
# Type 'y' when prompted, then remember to exit multiple times later

# Option 3: Use phw commands (avoids the prompt)
phw checkout your-branch  # Automatically handles switching
```

## Clean Up

```bash
# Remove a specific worktree
phw remove haacked/old-feature

# Clean up unused worktree references (safe to run)
git worktree prune
```

## Quick Setup Script

For a complete one-time setup, run:

```bash
# For zsh users
brew install direnv gh jq && \
echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc && \
echo 'source ~/dev/posthog/posthog/bin/phw' >> ~/.zshrc && \
source ~/.zshrc && \
echo "✅ Setup complete! You can now use 'phw' commands."

# For bash users
brew install direnv gh jq && \
echo 'eval "$(direnv hook bash)"' >> ~/.bashrc && \
echo 'source ~/dev/posthog/posthog/bin/phw' >> ~/.bashrc && \
source ~/.bashrc && \
echo "✅ Setup complete! You can now use 'phw' commands."
```

After setup, you're ready to use commands like:

- `phw create haacked/feature` (create from master)
- `phw create haacked/feature my-branch` (create from my-branch)
- `phw checkout my-branch`
- `phw pr 12345`
