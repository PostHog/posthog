# Depot CI: secrets and variables reference

Full command and flag reference for `depot ci secrets` and `depot ci vars`, plus the variant model and how Depot resolves a matching variant at run time. SKILL.md keeps the concept and the common commands; load this file for complete flag tables, the `set`/`bulk`/`get` subcommands, and the resolution rules.

**Common flags:** every subcommand also accepts `--org <id>` (required when the user belongs to multiple organizations) and `--token <token>`. They're omitted from the per-command tables below.

## Contents

- [The variant model](#the-variant-model)
- [Access rule kinds](#access-rule-kinds)
- [Resolution priority](#resolution-priority)
- [`depot ci secrets` subcommands](#depot-ci-secrets-subcommands)
- [`depot ci vars` subcommands](#depot-ci-vars-subcommands)

---

## The variant model

A secret or variable name groups one or more **variants**. A variant holds a value plus optional availability selectors (`--repo`, `--env`, `--branch`, `--workflow`) that match jobs by repository, GitHub environment, branch, and workflow file. A variant with no selectors applies to every job in the organization. This lets one name resolve to different values depending on workflow context, for example a different `DATABASE_URL` for `production` vs `staging`, or for one repo vs all repos.

Variants are managed from the CLI (selectors on `add`, `set`, `bulk`, `get`, `list`, `remove`) or in the dashboard ([Depot CI workflows](https://depot.dev/orgs/_/workflows) → Settings → Secrets/Variables → Add variant). Secrets are encrypted at rest and never readable after creation; variable values can be read back.

Selector flags are repeatable, and `--branch`/`--workflow` accept glob patterns. On `add`/`set`/`bulk` they scope where a variant applies; on `get`/`list`/`remove` they select or filter existing variants.

## Access rule kinds

Limit when a variant is selected by combining one or more rules:

- **Repository**: select when the workflow runs in a specific repository.
- **Branch**: select when the branch name matches; supports glob patterns like `release/*`.
- **Workflow**: select when the workflow file matches; supports glob patterns like `deploy-*.yaml`.
- **Environment**: select when the job's GitHub `environment` field matches exactly. Provides compatibility with GitHub Environment Secrets. Jobs without an `environment` field never match environment rules.

Within a single rule kind, alternatives broaden availability (`branch=main` OR `branch=release/*`). Across kinds, the variant must satisfy all rule kinds (`branch=main` AND `environment=production`).

## Resolution priority

When multiple variants match a job, Depot picks the most specific:

1. Environment rules win over all others. An org-wide variant with an environment rule beats a repo-scoped variant with no environment rule.
2. Repository scope wins over branch and workflow rules, but not over environment rules.
3. Branch and workflow rules: literal matches win over globs, narrower globs win over broader globs (`release/v2` beats `release/*`).

For a repo to override an org-wide environment variant, create a variant with both the repository scope **and** the environment rule.

To preview which variant resolves for a given workflow context, open the dashboard secret or variable create/edit page, expand the **Secret variants** or **Variable variants** list, and enter a sample context (repo, branch, workflow file, environment). The matching variant is highlighted.

---

## `depot ci secrets` subcommands

Secrets are referenced in workflows as `${{ secrets.SECRET_NAME }}`. Secret values are supplied through an interactive prompt, piped stdin, or `KEY=VALUE` bulk pairs; there is no `--value` flag for secrets (that flag exists only for variables).

### `depot ci secrets add`

Adds a secret variant. Three modes: interactive prompt (`depot ci secrets add NAME`), piped stdin (`printf '%s' "$V" | depot ci secrets add NAME`), or bulk `KEY=VALUE` pairs (`depot ci secrets add FOO=bar BAZ=qux`, `--description` not allowed in this mode). An optional second positional names the variant; without it the value writes to the `default` variant.

| Flag                   | Description                                                   |
| ---------------------- | ------------------------------------------------------------- |
| `--description <text>` | Description of the secret variant (single-secret mode only)   |
| `--repo <owner/repo>`  | Apply variant to a repository (repeatable)                    |
| `--env <name>`         | Apply variant to a GitHub environment (repeatable)            |
| `--branch <name>`      | Apply variant to a branch (repeatable, supports globs)        |
| `--workflow <file>`    | Apply variant to a workflow file (repeatable, supports globs) |

### `depot ci secrets set`

Creates or updates a single secret variant. Unlike `add`, it never accepts `KEY=VALUE` pairs and is the recommended form for scripts: pass `--from-stdin` with piped input, otherwise it runs interactively.

| Flag                   | Description                                                     |
| ---------------------- | --------------------------------------------------------------- |
| `--from-stdin`         | Read the secret value from stdin (required when stdin is piped) |
| `--description <text>` | Description of the secret variant                               |
| `--repo <owner/repo>`  | Apply variant to a repository (repeatable)                      |
| `--env <name>`         | Apply variant to a GitHub environment (repeatable)              |
| `--branch <name>`      | Apply variant to a branch (repeatable, supports globs)          |
| `--workflow <file>`    | Apply variant to a workflow file (repeatable, supports globs)   |

### `depot ci secrets bulk`

Imports secrets from a dotenv file or piped stdin. Input is parsed as `KEY=VALUE`; blank lines and `#` comments are ignored. The same variant name and selectors apply to every secret in the input. Exactly one of `--file` or `--from-stdin` is required.

```bash
depot ci secrets bulk --file .env --repo owner/repo
cat .env | depot ci secrets bulk production --from-stdin --branch 'release/*'
```

| Flag                  | Description                                                   |
| --------------------- | ------------------------------------------------------------- |
| `--file <path>`       | Read dotenv input from a file                                 |
| `--from-stdin`        | Read dotenv input from stdin                                  |
| `--repo <owner/repo>` | Apply variant to a repository (repeatable)                    |
| `--env <name>`        | Apply variant to a GitHub environment (repeatable)            |
| `--branch <name>`     | Apply variant to a branch (repeatable, supports globs)        |
| `--workflow <file>`   | Apply variant to a workflow file (repeatable, supports globs) |

### `depot ci secrets get`

Shows one secret variant with full, untruncated attributes (the value is still never returned). Errors if zero or more than one variant matches; narrow with `--variant-id`, the optional variant positional, or selectors.

| Flag                  | Description                                                              |
| --------------------- | ------------------------------------------------------------------------ |
| `--variant-id <id>`   | Fetch a variant directly by ID (mutually exclusive with a name argument) |
| `--repo <owner/repo>` | Select a variant matching a repository (repeatable)                      |
| `--env <name>`        | Select a variant matching a GitHub environment (repeatable)              |
| `--branch <name>`     | Select a variant matching a branch (repeatable)                          |
| `--workflow <file>`   | Select a variant matching a workflow file (repeatable)                   |
| `--output json`       | Output as JSON instead of the text view                                  |

### `depot ci secrets list`

Lists secrets and their variants (values never returned). Pass a secret name to scope to that secret. Selectors filter the variant rows; repeat any flag to widen the match.

```bash
depot ci secrets list
depot ci secrets list SECRET_NAME
depot ci secrets list --repo owner/repo --branch main
depot ci secrets list --output json
```

| Flag                  | Description                                        |
| --------------------- | -------------------------------------------------- |
| `--repo <owner/repo>` | Filter variants by repository (repeatable)         |
| `--env <name>`        | Filter variants by GitHub environment (repeatable) |
| `--branch <name>`     | Filter variants by branch (repeatable)             |
| `--workflow <file>`   | Filter variants by workflow file (repeatable)      |
| `--output json`       | Output as JSON instead of a table                  |

### `depot ci secrets remove`

Removes one or more secrets. By default each positional is a secret name and the whole secret (every variant) is removed. To remove a single variant, pass `--variant <name>` or selectors that uniquely identify one. `--all` makes whole-secret removal explicit and can't combine with selectors or `--variant`. Prompts for confirmation unless `--force`.

| Flag                  | Description                                                             |
| --------------------- | ----------------------------------------------------------------------- |
| `--variant <name>`    | Remove a specific variant by name                                       |
| `--all`               | Remove the secret and every variant (mutually exclusive with selectors) |
| `--repo <owner/repo>` | Select a variant matching a repository (repeatable)                     |
| `--env <name>`        | Select a variant matching a GitHub environment (repeatable)             |
| `--branch <name>`     | Select a variant matching a branch (repeatable)                         |
| `--workflow <file>`   | Select a variant matching a workflow file (repeatable)                  |
| `--force`             | Skip the confirmation prompt                                            |

---

## `depot ci vars` subcommands

Variables are referenced as `${{ vars.VARIABLE_NAME }}` and their values can be read back. They use the same variant model and selectors as secrets. Values are supplied with `--value`, an interactive prompt, or `KEY=VALUE` bulk pairs.

### `depot ci vars add`

Adds a variable variant. Three modes: interactive prompt, `--value "val"`, or bulk `KEY=VALUE` pairs (`--value` not allowed in that mode). An optional second positional names the variant.

| Flag                  | Description                                                    |
| --------------------- | -------------------------------------------------------------- |
| `--value <value>`     | Variable value (single-variable mode only; prompts if omitted) |
| `--repo <owner/repo>` | Apply variant to a repository (repeatable)                     |
| `--env <name>`        | Apply variant to a GitHub environment (repeatable)             |
| `--branch <name>`     | Apply variant to a branch (repeatable, supports globs)         |
| `--workflow <file>`   | Apply variant to a workflow file (repeatable, supports globs)  |

### `depot ci vars set`

Creates or updates a single variable variant. Never accepts `KEY=VALUE` pairs and exposes `--description`.

| Flag                   | Description                                                   |
| ---------------------- | ------------------------------------------------------------- |
| `--value <value>`      | Variable value (prompts if omitted)                           |
| `--description <text>` | Description of the variable variant                           |
| `--repo <owner/repo>`  | Apply variant to a repository (repeatable)                    |
| `--env <name>`         | Apply variant to a GitHub environment (repeatable)            |
| `--branch <name>`      | Apply variant to a branch (repeatable, supports globs)        |
| `--workflow <file>`    | Apply variant to a workflow file (repeatable, supports globs) |

### `depot ci vars list`

Lists variables and their variants, including values. Pass a variable name to scope; selectors filter variant rows.

| Flag                  | Description                                        |
| --------------------- | -------------------------------------------------- |
| `--repo <owner/repo>` | Filter variants by repository (repeatable)         |
| `--env <name>`        | Filter variants by GitHub environment (repeatable) |
| `--branch <name>`     | Filter variants by branch (repeatable)             |
| `--workflow <file>`   | Filter variants by workflow file (repeatable)      |
| `--output json`       | Output as JSON instead of a table                  |

### `depot ci vars remove`

Removes one or more variables. Same semantics as `secrets remove`: whole-variable by default, `--variant`/selectors for one variant, `--all` for explicit whole-variable, `--force` to skip confirmation.

| Flag                  | Description                                                               |
| --------------------- | ------------------------------------------------------------------------- |
| `--variant <name>`    | Remove a specific variant by name                                         |
| `--all`               | Remove the variable and every variant (mutually exclusive with selectors) |
| `--repo <owner/repo>` | Select a variant matching a repository (repeatable)                       |
| `--env <name>`        | Select a variant matching a GitHub environment (repeatable)               |
| `--branch <name>`     | Select a variant matching a branch (repeatable)                           |
| `--workflow <file>`   | Select a variant matching a workflow file (repeatable)                    |
| `--force`             | Skip the confirmation prompt                                              |
