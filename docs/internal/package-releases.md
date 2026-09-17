# Parser, HogVM, and deltalite releases

These packages publish only from a push to `master` in `PostHog/posthog`, after approval in the `Release SDK` GitHub environment.
Pull requests, including merge-queue PRs, can check versions and build artifacts but cannot publish them.
Build and publish checkouts use the triggering commit SHA, not a moving branch.
The release workflows do not push commits or tags.

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
3. The master workflow checks whether the version needs publication and builds its release artifacts.
   HogVM uses its existing test job to check the version.
4. The workflow sends an approval request to `#approvals-client-libraries`.
   Review the triggering commit and build results before approving `Release SDK`.
5. After publication, open a separate PR to update application dependency pins and lockfiles where needed.
   For Python packages, use `uv add --refresh-package <package> '<package>==<version>'`.
   For the npm parser, use `pnpm --filter=@posthog/frontend add '@posthog/hogql-parser@<version>'`.
   Run the relevant CI checks and merge this PR through the queue too.

A registry lookup failure stops the Python release rather than treating an unknown response as an unpublished version.
Re-run failed jobs on the same master run after resolving a transient failure.
PyPI publishing uses `skip-existing` so a retry can complete a partially uploaded release.
A new version is required for any source change after publication.

## Required administrator setup

Workflow changes alone cannot enforce registry trust or GitHub environment rules.
Complete this setup before approving a release, following the [SDK release handbook](https://posthog.com/handbook/engineering/sdks/releases).
Do not remove the environment guard to work around a failed publish.

### GitHub

Configure `Release SDK` in `PostHog/posthog`:

- Require approval from `PostHog/client-libraries-approvers` or `PostHog/team-client-libraries`.
- Prevent self-review and disable administrator bypass.
- Select deployment branches and tags explicitly: allow only the **branch** `master`, with no tag patterns.
- Save the protection rules before configuring the branch restriction, as described in the handbook.

The workflows reuse the CLI release's Slack secret and variables: `SLACK_CLIENT_LIBRARIES_BOT_TOKEN`, `SLACK_APPROVALS_CLIENT_LIBRARIES_CHANNEL_ID`, and `GROUP_CLIENT_LIBRARIES_SLACK_GROUP_ID`.
A Slack notification failure does not bypass environment approval or block a release.

### npm and PyPI

For every package in the table, configure its trusted publisher with:

- GitHub owner: `PostHog` (case-sensitive).
- Repository: `posthog`.
- Workflow filename: the exact filename in the table.
- GitHub environment: `Release SDK`.

Both npm jobs use OIDC with provenance and no npm token.
The PyPI jobs also use OIDC, with no API token fallback.
The environment claim ties registry authentication to GitHub's master-only deployment policy and approval rules.

Remove superseded trusted publisher entries, including PyPI entries using `pypi-hogql-parser`, `pypi-hogql-parser-rs`, or `pypi-deltalite`, and npm entries without an environment restriction.
Revoke obsolete publishing tokens and restrict alternate publishing credentials according to the handbook.
Leaving an old publisher entry active can let an older PR workflow continue to authenticate.
Cancel outstanding runs using the old release workflows during the transition.

Verify the settings in both GitHub and each registry before approving the first release.
The YAML change does not apply these remote settings.
