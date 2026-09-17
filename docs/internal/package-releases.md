# Parser, HogVM, and deltalite releases

These packages publish from `master` after approval in the `Release SDK` GitHub environment.
Pull requests cannot publish packages.

| Package                 | Registry | Workflow                     | Publish job     |
| ----------------------- | -------- | ---------------------------- | --------------- |
| `@posthog/hogql-parser` | npm      | `build-hogql-parser-npm.yml` | `publish-npm`   |
| `@posthog/hogvm`        | npm      | `ci-hog.yml`                 | `release-hogvm` |
| `hogql-parser`          | PyPI     | `build-hogql-parser.yml`     | `publish`       |
| `hogql-parser-rs`       | PyPI     | `build-hogql-parser-rs.yml`  | `publish`       |
| `deltalite`             | PyPI     | `build-deltalite.yml`        | `publish`       |

## Release a version

1. Change the package source and bump its version in a PR.
   For the Rust Python packages, keep `Cargo.toml` and `pyproject.toml` versions equal.
   Keep application dependency pins on an already published version in this PR.
2. Merge through the normal review and merge-queue process.
3. Wait for the master workflow to check the version and build its release artifacts.
4. The workflow sends an approval request to `#approvals-client-libraries`.
   Review the triggering commit and build results before approving `Release SDK`.
5. After publication, open a separate PR to update application dependency pins and lockfiles where needed.
   For Python packages, use `uv add --refresh-package <package> '<package>==<version>'`.
   For the npm parser, use `pnpm --filter=@posthog/frontend add '@posthog/hogql-parser@<version>'`.
   Run the relevant CI checks and merge this PR through the queue too.

## Retry a failed release

Resolve the failure, then re-run failed jobs on the same master workflow run.
PyPI publishing skips existing files so a retry can complete a partially uploaded release.
A new version is required for any source change after publication.
