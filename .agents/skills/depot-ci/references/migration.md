# Depot CI: migration reference

Detail for `depot ci migrate` and its subcommands, the transformations migration applies, and manual setup. SKILL.md keeps the high-level "Getting Started" flow; load this file for the subcommand flag tables and the exact set of changes migration makes to your workflows.

**Common flags:** `depot ci migrate` and its subcommands accept `--forge <github|origin>` (default `github`), `-y` / `--yes`, `--org <id>` (required when the user belongs to multiple organizations), and `--token <token>`.

Use the default `--forge=github` for repositories that use GitHub as the source of truth. Use `--forge=origin` for Origin-hosted repositories. The Origin flow detects an `origin.cursor.com` remote and checks that Depot can access the repository.

## Migrate subcommands

`depot ci migrate` runs the full flow: a preflight check, then copying and transforming selected workflows into `.depot/workflows/`, then reporting the secrets and variables they reference. Each phase is also a standalone subcommand:

```bash
# Validate auth, detect the repo, check the Depot Code Access GitHub App is installed
depot ci migrate preflight
depot ci migrate preflight --forge=origin

# Copy and transform workflows from .github/workflows/ to .depot/workflows/
depot ci migrate workflows
depot ci migrate workflows --forge=origin

# Import GitHub Actions secrets and variables into Depot CI
depot ci migrate secrets-and-vars
depot ci migrate secrets-and-vars --forge=origin
```

### `depot ci migrate workflows` steps

1. Discovers all workflow files in `.github/workflows/`.
2. Analyzes each workflow for Depot CI compatibility.
3. Prompts you to select which workflows to migrate.
4. With `--forge=origin`, sends the selected workflow contents to Depot for Origin compatibility analysis.
5. Copies selected workflows to `.depot/workflows/` and any local actions from `.github/actions/` to `.depot/actions/`.
6. Applies compatibility fixes and adds inline comments documenting each change.
7. Disables jobs that use unsupported features, with a `DISABLED` comment noting the reason.
8. Reports any secrets and variables detected in the migrated workflows.

Origin compatibility findings identify actions that fail or have reduced functionality because Origin does not expose an equivalent GitHub API. Findings do not block migration.

### What gets transformed

The command applies these changes, each documented with inline comments, and writes a header comment to every migrated file summarizing them:

- **`runs-on` labels** are remapped from GitHub runner labels (like `ubuntu-latest`) to their Depot equivalents (like `depot-ubuntu-latest`).
- **Unavailable GitHub runner labels** remain unchanged and produce a warning. Custom or conflicting labels also produce migration-summary warnings. Select a supported Depot Ubuntu runner before activating the workflow.
- **Unsupported triggers** (like `release` or `issues`) are removed from the `on:` block with a comment explaining why.
- **Jobs with unsupported features** are commented out entirely, with a `DISABLED` comment.
- **`.github/` path references** in copied workflow and action files are rewritten to their `.depot/` equivalents.

For the full compatibility matrix, see `github-actions-compatibility.md` in this directory.

## Flag tables

### `depot ci migrate` and `depot ci migrate workflows`

| Flag          | Description                                                                    |
| ------------- | ------------------------------------------------------------------------------ |
| `-y, --yes`   | Migrate all workflows and overwrite matching `.depot/` files without prompting |
| `--overwrite` | Overwrite matching files in an existing `.depot/` directory without prompting  |

For an agent or other non-interactive caller, `--yes` is required because workflow selection otherwise needs a terminal. Check the existing `.depot/` files before using `--yes`, because the flag also enables overwrite behavior.

(`depot ci migrate preflight` takes only the common flags.)

### `depot ci migrate secrets-and-vars`

Creates a one-shot GitHub Actions workflow on a temporary branch that reads your existing GitHub secrets and variables and imports them into Depot CI. The command creates the commit without changing your worktree, then prints the `git push` command. Push the branch within five minutes before the migration intent expires. The branch is safe to delete afterward. You can also add secrets and variables manually with `depot ci secrets add` / `depot ci vars add` (see `secrets-and-variables.md`).

`--yes` is accepted but has no effect on `secrets-and-vars`; the subcommand does not show a preview or confirmation prompt.

| Flag                       | Description                                                          |
| -------------------------- | -------------------------------------------------------------------- |
| `--branch-prefix <prefix>` | Prefix for the temporary migration branch; the intent ID is appended |
| `--secrets <name>`         | Secret name to include; repeatable. Omit to include all.             |
| `--vars <name>`            | Variable name to include; repeatable. Omit to include all.           |

## Manual setup (without the migrate command)

Create `.depot/workflows/` and `.depot/actions/` directories manually, copy workflow files from `.github/workflows/`, and configure secrets via the CLI (`depot ci secrets add`). The resulting layout:

```text
your-repo/
├── .github/
│   ├── workflows/     # Original GHA workflows (keep running)
│   └── actions/       # Local composite actions
├── .depot/
│   ├── workflows/     # Depot CI copies of workflows
│   └── actions/       # Depot CI copies of local actions
```

Keep `.github/workflows/` during the transition so workflows run in both GitHub and Depot, letting you verify parity. Note this means workflows with side effects (deploys, artifact updates) execute twice.
