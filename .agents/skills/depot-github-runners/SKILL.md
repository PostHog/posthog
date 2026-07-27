---
name: depot-github-runners
description: >
  Configures Depot-managed GitHub Actions runners as a drop-in replacement for GitHub-hosted
  runners. Use when setting up or migrating GitHub Actions workflows to use Depot runners,
  choosing runner sizes (CPU/RAM), configuring runs-on labels, setting up ARM or Windows or
  macOS runners, troubleshooting GitHub Actions runner issues, configuring egress filtering,
  using Depot Cache with GitHub Actions, or running Dagger/Dependabot on Depot runners.
  Also use when the user mentions depot-ubuntu, depot-windows, depot-macos runner labels,
  or asks about faster/cheaper GitHub Actions runners.
---

# Depot GitHub Actions Runners

Depot provides managed, ephemeral, single-tenant GitHub Actions runners. Drop-in replacement for GitHub-hosted runners — change the `runs-on` label and everything else stays the same.

**Requirement:** Repository must be owned by a GitHub organization (not a personal account).

## Setup

1. Depot dashboard → GitHub Actions → Connect to GitHub → Install Depot GitHub App
2. For public repos: GitHub org settings → Actions → Runner groups → Default → "Allow public repositories"
3. Update `runs-on` in your workflow files

## Org Context Check for Multi-Org Users

If a user belongs to multiple organizations and expected repos/settings/runners are not visible, verify Depot org context first:

```bash
depot org show              # Current org ID
depot org list              # Orgs the user belongs to
depot org switch <org-id>   # Optional: set default org
```

For commands that support it, pass `--org <org-id>` to target the org where the workflow/repo lives.

## Runner Labels

Use a single label. Format: `depot-{os}-{version}[-{arch}][-{size}]`

### Ubuntu (Intel x86 — AMD EPYC)

| Label                   | CPUs | RAM    | Disk   | $/min  |
| ----------------------- | ---- | ------ | ------ | ------ |
| `depot-ubuntu-24.04`    | 2    | 8 GB   | 100 GB | $0.004 |
| `depot-ubuntu-24.04-4`  | 4    | 16 GB  | 130 GB | $0.008 |
| `depot-ubuntu-24.04-8`  | 8    | 32 GB  | 150 GB | $0.016 |
| `depot-ubuntu-24.04-16` | 16   | 64 GB  | 180 GB | $0.032 |
| `depot-ubuntu-24.04-32` | 32   | 128 GB | 200 GB | $0.064 |
| `depot-ubuntu-24.04-64` | 64   | 256 GB | 250 GB | $0.128 |

Ubuntu 22.04 also available: `depot-ubuntu-22.04`, `depot-ubuntu-22.04-4`, etc.

### Ubuntu (ARM — Graviton4)

Same sizes and pricing as Intel. Add `-arm` suffix:
`depot-ubuntu-24.04-arm`, `depot-ubuntu-24.04-arm-4`, `depot-ubuntu-24.04-arm-8`, etc.

### Windows Server

| Label                                | CPUs | RAM       | $/min         |
| ------------------------------------ | ---- | --------- | ------------- |
| `depot-windows-2025`                 | 2    | 8 GB      | $0.008        |
| `depot-windows-2025-4`               | 4    | 16 GB     | $0.016        |
| `depot-windows-2025-8` through `-64` | 8–64 | 32–256 GB | $0.032–$0.256 |

Windows Server 2022 also available: `depot-windows-2022`, etc.
**Windows limitation:** No Hyper-V. Docker does not work on Windows runners.

### macOS (Apple M2)

| Label                                   | CPUs | RAM   | $/min |
| --------------------------------------- | ---- | ----- | ----- |
| `depot-macos-15` / `depot-macos-latest` | 8    | 24 GB | $0.08 |
| `depot-macos-14`                        | 8    | 24 GB | $0.08 |

macOS is NOT fully elastic — fixed pool with FIFO queuing. Startup plan+ only.

### Aliases

`depot-ubuntu-latest` → Ubuntu 24.04, `depot-windows-latest` → Windows 2025, `depot-macos-latest` → macOS 15

## Migration Example

```yaml
jobs:
  build:
    # Before:
    # runs-on: ubuntu-latest
    # After:
    runs-on: depot-ubuntu-24.04-4
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - run: npm test
```

## Common Mistakes

```yaml
# ❌ WRONG — multiple labels cause stability issues
runs-on: [self-hosted, depot-ubuntu-24.04]

# ✅ CORRECT — always use a single Depot runner label
runs-on: depot-ubuntu-24.04-4
```

## Caching

Actions using the GitHub Actions cache API automatically use **Depot Cache** — no config changes needed. This includes `actions/cache`, `actions/setup-node`, `actions/setup-python`, `actions/setup-java`, and any action using `@actions/cache`.

**Pre-configured build tool caches** (zero config on Depot runners):

| Tool      | What's pre-configured                                          |
| --------- | -------------------------------------------------------------- |
| Turborepo | `TURBO_API` env var set — just run `turbo build`               |
| Bazel     | `~/.bazelrc` pre-populated — just run `bazel build //...`      |
| sccache   | `SCCACHE_WEBDAV_ENDPOINT` set — use `RUSTC_WRAPPER: 'sccache'` |
| Maven     | `settings.xml` pre-populated (cache id `depot-cache`)          |
| Pants     | `pants.toml` pre-configured — just run `pants package ::`      |
| moonrepo  | Env vars set — just run `moon run build`                       |

Cache behavior: repository-scoped, no branch isolation, encrypted, up to 1000 MiB/s throughput, configurable retention (7/14/30 days).

To disable auto-cache: org settings → turn off "Allow Actions jobs to automatically connect to Depot Cache."

## Dagger Integration

**Deprecated:** Dagger Engine support on Depot GitHub Actions Runners is being deprecated and will be removed in a future update. Don't recommend this integration for new workflows.

```yaml
runs-on: depot-ubuntu-latest,dagger=0.15.1
```

Launches a dedicated Dagger Engine VM with persistent NVMe cache. Dagger CLI pre-installed. Additional $0.04/min.

## Egress Filtering (Linux Only)

Configure in org settings → GitHub Actions Runners → Egress Rules. Set default rule to Allow or Deny, then add specific allow/deny rules for IPs, CIDRs, or hostnames. Not supported on macOS or Windows. Incompatible with Tailscale.

## Access Private Endpoints with Tailscale

Use Tailscale when jobs need to reach private services (internal APIs, databases, private subnets) without static IP allowlists.

How it works on Depot:

- Depot GitHub Actions runners join your tailnet as ephemeral nodes at job start.
- Access is controlled with your Tailscale ACLs (recommended tag: `tag:depot-runner`).
- No workflow YAML changes are required just to connect runners to private endpoints.

Setup:

1. In Tailscale ACLs, create a runner tag (for example `tag:depot-runner`) under `tagOwners`.
2. Create a Tailscale OAuth client with `Keys > Auth Keys` write scope and choose that tag.
3. In Depot org settings, open Tailscale settings and connect using the OAuth client ID/secret.
4. Add ACLs allowing `tag:depot-runner` to access target hosts/subnets.

ACL examples:

```json
{
  "acls": [
    {
      "action": "accept",
      "src": ["tag:depot-runner"],
      "dst": ["database-hostname"]
    }
  ]
}
```

```json
{
  "acls": [
    {
      "action": "accept",
      "src": ["tag:depot-runner"],
      "dst": ["192.0.2.0/24:*"]
    }
  ]
}
```

Reference docs:

- https://depot.dev/docs/github-actions/how-to-guides/access-private-resources
- https://depot.dev/docs/integrations/tailscale

## Dependabot

Enable "Dependabot on self-hosted runners" in GitHub org settings. Jobs auto-run on `depot-ubuntu-latest`.

**Important:** OIDC is not supported for Dependabot. Use `token:` input with a `DEPOT_TOKEN` secret instead.

## SSH Debugging

```yaml
steps:
  - uses: actions/checkout@v4
  - uses: mxschmitt/action-tmate@v3
  - run: npm test
```

## Troubleshooting

| Error                                        | Fix                                                                                                 |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| "No space left on device"                    | OS uses ~70 GB disk; upgrade to larger runner or clean disk in workflow                             |
| "Lost communication with server"             | Check status.depot.dev; check org usage caps                                                        |
| "Operation was canceled"                     | Manual cancel, concurrency cancel-in-progress, or OOM — check memory in dashboard                   |
| "Unable to get ACTIONS_ID_TOKEN_REQUEST_URL" | Dependabot doesn't support OIDC — use `DEPOT_TOKEN` secret                                          |
| Workflows not starting                       | Verify single runner label; check runner group allows the repo; verify Depot GitHub App permissions |
| Stuck workflows                              | Force cancel via GitHub API: `POST /repos/{owner}/{repo}/actions/runs/{id}/force-cancel`            |
