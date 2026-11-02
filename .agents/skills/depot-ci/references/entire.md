# Depot CI on Entire

Use this reference when connecting an Entire repository or selecting Entire in CLI commands.

## Connect and migrate

Open Settings → Depot CI → General → Connections → Connect Entire. Install the Depot plugin for the Entire project and connect the installation to a Depot organization you own.

Create `.depot/workflows/ci.yml`, or migrate existing GitHub Actions workflows with CLI v2.103.3 or later:

```bash
depot ci migrate --forge=entire
```

Run migration from a checkout with an Entire remote. Preflight checks installation access. Review the copied workflows before committing and pushing. For secrets import, use the GitHub checkout procedure in `migration.md`; Entire cannot supply secrets through migration.

## Select the repository

Entire repository names are `<namespace>/<owner>/<name>`. Use `et` for an Entire-hosted repository and `gh` for a GitHub repository mirrored into Entire. Preserve the namespace in `--repo` and secret or variable repository selectors.

```bash
depot ci run --forge entire --repo et/acme/api --workflow .depot/workflows/ci.yml
depot ci dispatch --repo et/acme/api --workflow ci.yml --ref main
```

Use `push`, `schedule`, or `workflow_dispatch` triggers. Entire pull request triggers are unsupported. Schedules run from the default branch. Tag pushes run CI but report results only in Depot.

## Checkout and credentials

Use `actions/checkout` with `contents: read`, or `contents: write` when the job must push changes. Checkout credentials cover the run's repository only. Steps that call Entire directly use the masked `ENTIRE_TOKEN` environment variable. `github.token` and `secrets.GITHUB_TOKEN` do not authenticate to Entire or the public GitHub API.

Use public GitHub actions or local `uses: ./...` actions. Private GitHub actions and Entire-hosted actions do not resolve. Actions that need GitHub APIs require separate credentials and a GitHub destination.

For OIDC, retain `contents: read` alongside `id-token: write` when the job checks out code. The issuer remains `https://identity.depot.dev`; the subject uses `ci/entire` and includes the namespace:

```text
spiffe://identity.depot.dev/org/<orgID>/ci/entire/<namespace>/<owner>/<name>/ref/<ref>/sandbox/<sandboxID>
```
