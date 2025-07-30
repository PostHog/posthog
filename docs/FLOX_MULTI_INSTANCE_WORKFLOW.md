# PostHog Isolated Development Environments with Flox

This guide explains how to create isolated PostHog development environments using Flox and Git worktrees for seamless branch switching.

**Key Benefits:**

- Work on multiple branches simultaneously with isolated environments
- Each worktree has its own Flox environment and Python dependencies  
- Quick switching between features, bug fixes, and PR reviews
- Standard `bin/start` command works in each worktree

> [!IMPORTANT]
**Important:** Only one PostHog instance (`bin/start`) can run at a time since they all use the same ports. The workflow focuses on quickly stopping one instance and starting another.

## Prerequisites

1. **Flox installed**: https://flox.dev/docs/install-flox/
2. **Git worktrees support** (Git 2.5+)
3. **GitHub CLI** (optional, for PR checkout): `brew install gh`
4. **direnv** (recommended): `brew install direnv`

## Quick Start

### 1. One-Time Setup

```bash
# Install dependencies
brew install direnv gh

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
phw create haacked/new-feature
# You're now IN the worktree with Flox activated!
bin/start
# Access at http://localhost:8000

# Or specify a different base branch
phw create haacked/new-feature main
```

#### Work on EXISTING branch
```bash
phw checkout main
# Switched to main branch worktree, Flox activated!
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
phw checkout main
# Already in main worktree with Flox activated
git pull origin main
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
cd ~/.worktrees/posthog/haacked/analytics-dashboard
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
cd ~/.worktrees/posthog/haacked/feature-analytics
bin/start  # Work on feature

# Stop and switch to bug fix
# Ctrl+C to stop
cd ~/.worktrees/posthog/bugfix/login-issue
bin/start  # Switch to bug fix work

# Stop and switch to PR review
# Ctrl+C to stop
cd ~/.worktrees/posthog/pr-1234-teammate
bin/start  # Review PR
```

### Managing Your Worktrees

```bash
# See all your worktrees
phw list

# Output:
# Branch                        Path
# ------                        ----
# haacked/analytics-dashboard   ~/.worktrees/posthog/haacked/analytics-dashboard
# main                         ~/.worktrees/posthog/main
# pr-5678-teammate             ~/.worktrees/posthog/pr-5678-teammate

# Remove when done
phw remove pr-5678-teammate
```

## Quick Reference

### Commands
```bash
phw create <branch> [base-branch]   # Create new branch & worktree (defaults to master)
phw checkout <branch>               # Use existing branch in worktree
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

### The Magic Flow

```
phw create branch → creates worktree → copies .envrc → cd to worktree → 
direnv detects .envrc → activates Flox → runs uv sync → ready to code!
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
cd ~/.worktrees/posthog/your-branch
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

## Clean Up

```bash
# Remove a specific worktree
phw remove haacked/old-feature

# Remove all worktrees (be careful!)
git worktree list | grep -v "bare" | awk '{print $1}' | xargs -I {} git worktree remove {}

# Clean up unused worktree references
git worktree prune
```

## Quick Setup Script

For a complete one-time setup, run:

```bash
# For zsh users
brew install direnv gh && \
echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc && \
echo 'source ~/dev/posthog/posthog/bin/phw' >> ~/.zshrc && \
source ~/.zshrc && \
echo "✅ Setup complete! You can now use 'phw' commands."

# For bash users
brew install direnv gh && \
echo 'eval "$(direnv hook bash)"' >> ~/.bashrc && \
echo 'source ~/dev/posthog/posthog/bin/phw' >> ~/.bashrc && \
source ~/.bashrc && \
echo "✅ Setup complete! You can now use 'phw' commands."
```

After setup, you're ready to use commands like:
- `phw create haacked/feature` (create from master)
- `phw create haacked/feature main` (create from main)
- `phw checkout main`
- `phw pr 12345`