# Depot CI: migration reference

Detail for `depot ci migrate` and its subcommands, the transformations migration applies, and manual setup. SKILL.md keeps the high-level "Getting Started" flow; load this file for the subcommand flag tables and the exact set of changes migration makes to your workflows.

**Common flags:** `depot ci migrate` and its subcommands accept `--org <id>` (required when the user belongs to multiple organizations) and `--token <token>`.

## Migrate subcommands

`depot ci migrate` runs the full flow: a preflight check, then copying and transforming selected workflows into `.depot/workflows/`, then reporting the secrets and variables they reference. Each phase is also a standalone subcommand:

```bash
# Validate auth, detect the repo, check the Depot Code Access GitHub App is installed
depot ci migrate preflight

# Copy and transform workflows from .github/workflows/ to .depot/workflows/
depot ci migrate workflows

# Import GitHub Actions secrets and variables into Depot CI
depot ci migrate secrets-and-vars
```

### `depot ci migrate workflows` steps

1. Discovers all workflow files in `.github/workflows/`.
2. Analyzes each workflow for Depot CI compatibility.
3. Prompts you to select which workflows to migrate.
4. Copies selected workflows to `.depot/workflows/` and any local actions from `.github/actions/` to `.depot/actions/`.
5. Applies compatibility fixes and adds inline comments documenting each change.
6. Disables jobs that use unsupported features, with a `DISABLED` comment noting the reason.
7. Reports any secrets and variables detected in the migrated workflows.

### What gets transformed

The command applies these changes, each documented with inline comments, and writes a header comment to every migrated file summarizing them:

- **`runs-on` labels** are remapped from GitHub runner labels (like `ubuntu-latest`) to their Depot equivalents (like `depot-ubuntu-latest`).
- **Unsupported triggers** (like `release` or `issues`) are removed from the `on:` block with a comment explaining why.
- **Jobs with unsupported features** are commented out entirely, with a `DISABLED` comment.
- **`.github/` path references** in copied workflow and action files are rewritten to their `.depot/` equivalents.

For the full compatibility matrix, see `github-actions-compatibility.md` in this directory.

## Flag tables

### `depot ci migrate` and `depot ci migrate workflows`

| Flag          | Description                                                 |
| ------------- | ----------------------------------------------------------- |
| `-y, --yes`   | Non-interactive: migrate all discovered workflows           |
| `--overwrite` | Overwrite an existing `.depot/` directory without prompting |

(`depot ci migrate preflight` takes only the common flags.)

### `depot ci migrate secrets-and-vars`

Creates a one-shot GitHub Actions workflow on a temporary branch that reads your existing GitHub secrets and variables and imports them into Depot CI. In interactive mode you can preview the generated workflow first; the branch is safe to delete afterward. You can also add secrets and variables manually with `depot ci secrets add` / `depot ci vars add` (see `secrets-and-variables.md`).

| Flag               | Description                                                |
| ------------------ | ---------------------------------------------------------- |
| `-y, --yes`        | Skip preview and confirmation prompts                      |
| `--branch <name>`  | Override the branch name used for the migration workflow   |
| `--secrets <name>` | Secret name to include; repeatable. Omit to include all.   |
| `--vars <name>`    | Variable name to include; repeatable. Omit to include all. |

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
