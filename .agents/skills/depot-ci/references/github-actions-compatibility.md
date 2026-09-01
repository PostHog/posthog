# Depot CI compatibility with GitHub Actions

Depot CI runs GitHub Actions YAML on Depot's own orchestrator and compute, so most workflows execute unmodified. The lists below enumerate exactly which GHA features Depot CI accepts, which it ignores, and which it rejects. They mirror `app/content/docs/ci/compatibility.mdx` in the Depot docs repo.

## Supported

### Workflow level

`name`, `run-name`, `on`, `permissions`, `env`, `concurrency`, `defaults`, `jobs`, `on.workflow_call` (with inputs, outputs, secrets)

### Triggers

`push` (branches, tags, paths), `pull_request` (branches, paths), `pull_request_target`, `pull_request_review`, `deployment_status`, `repository_dispatch` (with `types`), `schedule`, `workflow_call`, `workflow_dispatch` (with inputs), `workflow_run`, `merge_group`

`repository_dispatch` lets you trigger runs from outside GitHub via the GitHub API; the custom event type and `client_payload` are available through `github.event.action` and `github.event.client_payload`. GitHub delivers these events only against the default branch, so the default-branch workflow runs.

### Job level

`name`, `needs`, `if`, `permissions`, `outputs`, `env`, `defaults`, `timeout-minutes`, `concurrency`, `strategy` (matrix, fail-fast, max-parallel), `continue-on-error`, `container`, `services`, `uses` (reusable workflows), `with`, `secrets`, `secrets.inherit`, `steps`, `snapshot` (custom images from sandbox snapshots)

### Step level

`id`, `name`, `if`, `uses`, `run`, `shell`, `with`, `env`, `working-directory`, `continue-on-error`, `timeout-minutes`

### Permissions

`actions`, `checks`, `contents`, `id-token`, `metadata`, `pull_requests`, `statuses`, `workflows`

### Expressions

Contexts: `github`, `env`, `vars`, `secrets`, `needs`, `strategy`, `matrix`, `steps`, `job`, `runner`, `inputs`.

Functions: `always()`, `success()`, `failure()`, `cancelled()`, `case()`, `contains()`, `startsWith()`, `endsWith()`, `format()`, `join()`, `toJSON()`, `fromJSON()`, `hashFiles()`.

### Action types

JavaScript (Node 12/16/20/24), Composite, Docker.

## Not Supported

- **Cross-repo reusable workflows**: `uses` referencing workflows in other repositories is not supported. Local reusable workflows work.
- **Fork-triggered PRs**: `pull_request` and `pull_request_target` from forks not supported yet.
- **Non-Ubuntu runner labels**: all non-Depot labels silently treated as `depot-ubuntu-latest` (no error, runs on Ubuntu).
- **Deployment environments**: the `environment` field is not supported.
- **GitHub-specific event triggers**: `branch_protection_rule`, `check_run`, `check_suite`, `create`, `delete`, `deployment`, `discussion`, `discussion_comment`, `fork`, `gollum`, `image_version`, `issue_comment`, `issues`, `label`, `milestone`, `page_build`, `public`, `pull_request_comment`, `pull_request_review_comment`, `registry_package`, `release`, `status`, `watch`.

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
| `depot-ubuntu-24.04-4-arm`  | `4x16`       | 4    | 16 GB  |
| `depot-ubuntu-24.04-8-arm`  | `8x32`       | 8    | 32 GB  |
| `depot-ubuntu-24.04-16-arm` | `16x64`      | 16   | 64 GB  |
| `depot-ubuntu-24.04-32-arm` | `32x128`     | 32   | 128 GB |
| `depot-ubuntu-24.04-64-arm` | `64x256`     | 64   | 256 GB |

Any label Depot CI can't parse is silently treated as `depot-ubuntu-latest`.

## Migration behavior

`depot ci migrate` reads workflows under `.github/workflows/`, transforms them, and writes copies under `.depot/workflows/`. When it encounters an unsupported feature, it does one of the following with inline comments explaining the change:

- **Unsupported triggers** are removed from the `on:` block.
- **Jobs that depend on unsupported features** are commented out and labeled `DISABLED`.
- **`runs-on` labels** are remapped to Depot equivalents (for example, `ubuntu-latest` → `depot-ubuntu-latest`).
- **`.github/` path references** in copied files are rewritten to their `.depot/` equivalents.

If a user reports an auto-disabled job or a stripped trigger after migration, cross-reference the "Not Supported" list above to explain why.
