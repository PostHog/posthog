# Depot CI compatibility with GitHub Actions

Depot CI runs GitHub Actions YAML on Depot's own orchestrator and compute, so most workflows execute unmodified. The lists below enumerate exactly which GHA features Depot CI accepts, which it ignores, and which it rejects. They mirror `app/content/docs/ci/compatibility.mdx` in the Depot docs repo.

## Supported

### Workflow level

`name`, `run-name`, `on`, `permissions`, `env`, `concurrency`, `defaults`, `jobs`, `on.workflow_call` (with inputs, outputs, secrets)

### Triggers

`push` (branches, tags, paths), `pull_request` (branches, paths), `pull_request_target`, `pull_request_review`, `issue_comment` (created, edited, deleted), `deployment_status`, `repository_dispatch` (with `types`), `schedule`, `workflow_call`, `workflow_dispatch` (with inputs), `workflow_run`, `merge_group`

`issue_comment` covers comments on issues and pull requests. The workflow runs from the repository's default branch. Use `github.event.issue.pull_request` to distinguish pull request comments. Issue edits and label changes use the separate unsupported `issues` trigger; inline pull request review comments use the separate unsupported `pull_request_review_comment` trigger.

`repository_dispatch` lets you trigger runs from outside GitHub via the GitHub API; the custom event type and `client_payload` are available through `github.event.action` and `github.event.client_payload`. GitHub delivers these events only against the default branch, so the default-branch workflow runs.

For scheduled GitHub workflows, add `on.schedule` to `.depot/workflows/` and merge the workflow into the default branch. Depot evaluates cron expressions in UTC and runs the default branch independently of GitHub's scheduler. Per-entry `timezone` fields are ignored. Depot Code scheduled runs are not supported.

Depot CI supports native GitHub stacked pull requests for `pull_request` workflows. Depot evaluates the `branches` filter against the stack's ultimate base branch, then runs the workflow for each pull request using its own merge ref. `github.event.pull_request.stack` provides `number`, `size`, `position`, `base.ref`, and `base.sha`; the value is `null` for an ordinary pull request.

For `workflow_run`, the `on.workflow_run.workflows` filter accepts a YAML workflow name, Depot filename, or repository path. In `github.event.workflow_run`, `name` is the YAML name (or the repository path when unnamed), `path` is the repository-relative path such as `.depot/workflows/ci.yml`, and the Depot-only `basepath` is the filename such as `ci.yml`. `name` does not use `run-name`.

### Cross-repository reusable workflows

Use job-level `uses: owner/repo/.github/workflows/build.yml@v1`. Depot resolves authored `.github/workflows/` paths to `.depot/workflows/` in the source repository; direct `.depot/workflows/` references also work. Nested calls, matrix jobs, inputs, and outputs are supported.

Pin a full 40-character commit SHA or a version tag such as `v1`, `v1.2`, or `v1.2.3`. Branch refs and abbreviated SHAs are unsupported. Version-looking refs must resolve to tags.

For private or internal sources, the caller must be a trusted private repository in the same GitHub organization, and the Depot Code Access app needs source-repository access. External workflows require a GitHub caller. External jobs cannot use deployment environments, snapshots, or custom runner images. Cross-repository `secrets: inherit` requires an eligible trusted private caller in the same GitHub organization; prefer explicit secret mappings when inheritance is not needed.

### Job level

`name`, `needs`, `if`, `permissions`, `outputs`, `env`, `defaults`, `timeout-minutes`, `concurrency`, `strategy` (matrix, fail-fast, max-parallel), `continue-on-error`, `container`, `services`, `uses` (reusable workflows), `with`, `secrets`, `secrets.inherit`, `steps`, `snapshot` (custom images from sandbox snapshots)

### Step level

`id`, `name`, `if`, `uses`, `run`, `shell`, `with`, `env`, `working-directory`, `continue-on-error`, `timeout-minutes`

### Permissions

`actions`, `checks`, `code-quality`, `contents`, `id-token`, `issues`, `packages`, `pull-requests`, `security-events`, `statuses`

Use the hyphenated `pull-requests` key. Unknown permission keys are ignored when configuring `GITHUB_TOKEN`; operations that need those permissions can still fail.

For `issues: read` or `issues: write`, approve the corresponding Issues permission on the Depot Code Access installation. Without that grant, job tokens can omit `issues`, and issue operations fail.

Request `code-quality` explicitly. The `read-all` and `write-all` shorthands do not include it, which preserves compatibility with older Depot Code Access GitHub App installations.

### Expressions

Contexts: `github`, `env`, `vars`, `secrets`, `needs`, `strategy`, `matrix`, `steps`, `job`, `runner`, `inputs`, `depot`.

Functions: `always()`, `success()`, `failure()`, `cancelled()`, `case()`, `contains()`, `startsWith()`, `endsWith()`, `format()`, `join()`, `toJSON()`, `fromJSON()`, `hashFiles()`.

### Action types

JavaScript (Node 12/16/20/24), Composite, Docker.

Actions declaring Node 12, 16, or 20 run on Node.js 24 by default. `ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION: 'true'` temporarily selects Node.js 20 for those actions; actions declaring Node 24 remain on Node 24. The action runtime is separate from `node` on `PATH` in `run:` steps.

## Not Supported

- **Fork-triggered PRs**: `pull_request` and `pull_request_target` from forks not supported yet.
- **Non-Ubuntu runners**: Depot CI has no Windows or macOS sandboxes. Do not assume a migrated runner label preserves the original operating system.
- **Deployment environments**: the `environment` field is not supported.
- **GitHub-specific event triggers**: `branch_protection_rule`, `check_run`, `check_suite`, `create`, `delete`, `deployment`, `discussion`, `discussion_comment`, `fork`, `gollum`, `image_version`, `issues`, `label`, `milestone`, `page_build`, `public`, `pull_request_comment`, `pull_request_review_comment`, `registry_package`, `release`, `status`, `watch`.

### GitHub Packages authentication

`secrets.GITHUB_TOKEN` is a GitHub App token in Depot CI, and GitHub Packages does not accept GitHub App tokens for package access. This limitation applies to every GitHub Packages registry, including GHCR.

For container images, prefer Depot Registry. When GitHub Packages is required, authenticate with a GitHub personal access token that has the required package scope and store it as a Depot CI secret. A personal access token is a long-lived user credential, so account lifetime, rotation, and least-privilege scope require explicit consideration.

## Runner labels

Depot CI sandboxes are x86_64 and arm only. There is no macOS or Windows support: those Depot GitHub Actions runner labels (`depot-macos-*`, `depot-windows-*`) are not compatible with Depot CI.

Supported labels:

| Label                       | Sandbox size | CPUs | RAM    |
| --------------------------- | ------------ | ---- | ------ |
| `depot-ubuntu-latest`       | `2x8`        | 2    | 8 GB   |
| `depot-ubuntu-24.04`        | `2x8`        | 2    | 8 GB   |
| `depot-ubuntu-24.04-4`      | `4x16`       | 4    | 16 GB  |
| `depot-ubuntu-24.04-8`      | `8x32`       | 8    | 32 GB  |
| `depot-ubuntu-24.04-16`     | `16x64`      | 16   | 64 GB  |
| `depot-ubuntu-24.04-32`     | `32x128`     | 32   | 128 GB |
| `depot-ubuntu-24.04-64`     | `64x256`     | 64   | 256 GB |
| `depot-ubuntu-latest-arm`   | `2x8`        | 2    | 8 GB   |
| `depot-ubuntu-24.04-arm`    | `2x8`        | 2    | 8 GB   |
| `depot-ubuntu-24.04-arm-4`  | `4x16`       | 4    | 16 GB  |
| `depot-ubuntu-24.04-arm-8`  | `8x32`       | 8    | 32 GB  |
| `depot-ubuntu-24.04-arm-16` | `16x64`      | 16   | 64 GB  |
| `depot-ubuntu-24.04-arm-32` | `32x128`     | 32   | 128 GB |
| `depot-ubuntu-24.04-arm-64` | `64x256`     | 64   | 256 GB |

Jobs without a `depot-*` label fall back to `depot-ubuntu-latest`. Check migration warnings and choose a supported label instead of relying on fallback behavior.

## Migration behavior

`depot ci migrate` reads workflows under `.github/workflows/`, transforms them, and writes copies under `.depot/workflows/`. When it encounters an unsupported feature, it does one of the following with inline comments explaining the change:

- **Unsupported triggers** are removed from the `on:` block.
- **Jobs that depend on unsupported features** are commented out and labeled `DISABLED`.
- **`runs-on` labels** are remapped to Depot equivalents (for example, `ubuntu-latest` → `depot-ubuntu-latest`).
- **Unavailable GitHub runner labels** remain unchanged with a warning. Custom or conflicting labels also produce warnings in the migration summary. Choose a supported Depot runner before activating the workflow.
- **`.github/` path references** in copied files are rewritten to their `.depot/` equivalents.

If a user reports an auto-disabled job or a stripped trigger after migration, cross-reference the "Not Supported" list above to explain why.

The CLI migration analyzer can still report external reusable workflows as unsupported even though the backend supports them. Check the supported reference and access rules above before replacing an external workflow with an inline copy.
