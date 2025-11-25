# npm Release Monitor

A Temporal workflow that monitors PostHog npm packages for unauthorized releases by correlating npm publishes with GitHub CI/CD workflow runs.

## Background

This monitor was created in response to the Shai-Hulud supply chain attack, where an npm publishing key was compromised leading to unauthorized package publishes. The monitor detects releases that don't correlate with legitimate CI/CD workflows, which may indicate:

- Compromised npm credentials
- Unauthorized manual publishes
- Supply chain attacks

## How it works

1. **Fetch npm versions** - Queries the npm registry for recent publishes of monitored packages
2. **Fetch GitHub workflow runs** - Queries GitHub Actions API for recent workflow runs
3. **Correlate releases** - Matches npm publishes to CI/CD runs within a configurable time window (default: 10 minutes)
4. **Alert** - Sends alerts via Slack and creates incidents in incident.io for any unauthorized releases

The workflow runs every 30 minutes with a 1-hour lookback window.

## Monitored packages

Last validated: November 2024

### PostHog/posthog-js monorepo

These packages are all published from the [posthog-js](https://github.com/PostHog/posthog-js) monorepo:

| npm package | Notes |
|-------------|-------|
| `posthog-js` | Core browser SDK |
| `posthog-node` | Node.js SDK |
| `posthog-react-native` | React Native SDK |
| `@posthog/core` | Shared core library |
| `@posthog/ai` | AI/LLM integration |
| `@posthog/nextjs-config` | Next.js config helper |
| `@posthog/nuxt` | Nuxt.js integration |

### PostHog/posthog monorepo

These packages are published from the main [posthog](https://github.com/PostHog/posthog) monorepo:

| npm package | Notes |
|-------------|-------|
| `@posthog/plugin-server` | Plugin server (in `/plugin-server`) |
| `@posthog/icons` | Icon library |
| `@posthog/lemon-ui` | UI component library (in `/frontend/@posthog/lemon-ui`) |
| `@posthog/cli` | PostHog CLI tool |

### Separate repositories

| npm package | GitHub repo | Notes |
|-------------|-------------|-------|
| `posthog-react-native-session-replay` | PostHog/posthog-react-native-session-replay | Session replay for React Native |
| `@posthog/nextjs` | PostHog/posthog-js-lite | Next.js SDK (lightweight) |
| `@posthog/wizard` | PostHog/wizard | Setup wizard CLI |
| `@posthog/hedgehog-mode` | PostHog/hedgehog-mode | Easter egg hedgehog animation |

### rrweb packages

These are published from PostHog's fork of rrweb:

| npm package | GitHub repo |
|-------------|-------------|
| `@posthog/rrweb-player` | PostHog/posthog-rrweb |
| `@posthog/rrweb-record` | PostHog/posthog-rrweb |
| `@posthog/rrweb-replay` | PostHog/posthog-rrweb |
| `@posthog/rrweb-snapshot` | PostHog/posthog-rrweb |
| `@posthog/rrweb-utils` | PostHog/posthog-rrweb |
| `@posthog/rrdom` | PostHog/posthog-rrweb |
| `@posthog/react-rrweb-player` | PostHog/posthog-react-rrweb-player |

### Forked/utility packages

| npm package | GitHub repo | Notes |
|-------------|-------------|-------|
| `@posthog/piscina` | PostHog/piscina | Fork of piscina worker pool |
| `@posthog/clickhouse` | PostHog/node-clickhouse | ClickHouse client |
| `@posthog/siphash` | PostHog/siphash-js | SipHash implementation |

### Example packages

| npm package | GitHub repo |
|-------------|-------------|
| `posthog-plugin-hello-world` | PostHog/posthog-plugin-hello-world |

## Packages NOT monitored (and why)

### `@posthog/rrweb`

The npm registry shows this package's repository as `rrweb-io/rrweb` (the upstream project), not a PostHog-controlled repository. Since we can't correlate publishes with PostHog CI/CD, this package is excluded.

**Risk**: If this package is actually published by PostHog, consider updating the npm package.json to point to the correct repo.

### `@posthog/agent`

The npm registry references `PostHog/posthog-agent`, but this GitHub repository doesn't exist. Unable to monitor without a valid repo.

### `@posthog/web-dev-server`

No repository field in npm registry. Unable to determine the source repo.

### `posthog-docusaurus`

No repository field in npm registry. Unable to determine the source repo.

## Configuration

Environment variables required:

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | Yes | GitHub token with `repo` read access for fetching workflow runs |
| `NPM_RELEASE_MONITOR_SLACK_WEBHOOK` | No | Slack webhook URL for alerts |
| `INCIDENT_IO_API_KEY` | No | incident.io API key for creating incidents |

## Adding new packages

To add a new package to monitoring:

1. Find the package on npm: `https://registry.npmjs.org/{package-name}`
2. Check the `repository.url` field to identify the GitHub repo
3. Verify the repo exists and has CI/CD workflows for publishing
4. Add a `MonitoredPackage` entry to `config.py`

```python
MonitoredPackage(
    npm_package="@posthog/new-package",
    github_repo="PostHog/repo-name",
    workflow_names=["Release", "Publish"],  # Optional, defaults to common names
    time_window_minutes=10,  # Optional, default 10
)
```

## Workflow names

The monitor looks for GitHub Actions workflows with names containing (case-insensitive):

- "Release"
- "Publish"
- "release"
- "publish"

Custom workflow names can be specified per-package in the config.
