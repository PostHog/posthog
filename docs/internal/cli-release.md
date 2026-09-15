# CLI release permissions

The [CLI release workflow](../../.github/workflows/release-cli.yml) uses the `releaser-posthog-cli` GitHub App to commit release changes and open a pull request.
A separate App approves that pull request.

The CLI releaser App installation needs these repository permissions:

- **Contents: Read and write** to create the release branch and commit.
- **Pull requests: Read and write** to create or update the release pull request.

The workflow requests both permissions when it creates the token.
This request cannot grant permissions that the App installation lacks.
The job's `permissions` block applies only to `GITHUB_TOKEN`, which this step does not use.

## Restore missing permissions

If PR creation fails with `Resource not accessible by integration`, check the CLI releaser App installation.
A GitHub App administrator must complete these steps:

1. Open the CLI releaser App under the PostHog organization's **Developer settings > GitHub Apps**.
2. Set **Repository permissions > Pull requests** to **Read and write**.
3. Save the change.
4. Approve the permission update for the App installation that has access to `PostHog/posthog`.
5. Re-run the failed release preparation job. The job creates a new token.

With explicit token permissions, a missing grant stops the job at token creation, before it prepares or commits release changes.
