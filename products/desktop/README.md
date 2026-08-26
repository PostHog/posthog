> [!IMPORTANT]
> Interested in the PostHog desktop app? [Join the waitlist](https://posthog.com/desktop) or hop into our [Discord](https://discord.gg/aSrHKVNVdR).

**[Download the latest version](https://github.com/PostHog/posthog/releases?q=desktop-v)**

Found a bug or want to share feedback? [Open an issue](https://github.com/PostHog/posthog/issues/new) on GitHub.

# PostHog Desktop

This is the source for the PostHog desktop and mobile apps and the agent framework that powers them.

> [!NOTE]
> This directory lives at `products/desktop` inside [posthog/posthog](https://github.com/PostHog/posthog). If you already have that repo checked out, there is no separate clone: `cd products/desktop` and follow the setup below. It is a standalone pnpm workspace with its own lockfile and Node version.

## Development

### Prerequisites

- Node.js 22+
- pnpm 10.23.0

### Setup

```bash
# Install pnpm if you haven't already
npm install -g pnpm

# Install dependencies for all packages
pnpm install

# Optional: copy environment config
# Only needed for code signing (APPLE_*) or PostHog analytics (VITE_POSTHOG_*).
# The app runs fine in dev without it.
cp .env.example .env

```

### Running in development

By default, `pnpm dev` uses phrocs (our custom process runner) to run the agent and code app in parallel. phrocs auto-installs and keeps itself up to date: on every `pnpm install` the local binary is checked against the latest `phrocs-latest` release checksums and re-downloaded if it differs (skipped when offline or in CI). `pnpm dev` only downloads it if it is missing entirely. It reads the `mprocs.yaml` config file. The binary lives at `bin/phrocs` and is git-ignored.

```bash
# Run both agent (watch mode) and code app in parallel
pnpm dev

# Or run them separately:
pnpm dev:agent  # Run agent in watch mode
pnpm dev:code   # Run code app
# Use mprocs instead of phrocs
pnpm dev:mprocs
```

> **Want to connect to a local PostHog instance?** See [docs/LOCAL-DEVELOPMENT.md](./docs/LOCAL-DEVELOPMENT.md) for OAuth setup and connecting to localhost:8010.

### Utility scripts

Scripts in `scripts/` for development and debugging:

| Script | Description |
|--------|-------------|
| `scripts/clean-posthog-code-macos.sh` | Remove all PostHog app data from macOS (caches, preferences, logs, saved state). Use `--app` flag to also delete PostHog.app from /Applications. |
| `scripts/test-access-token.js` | Validate a PostHog OAuth access token by testing API endpoints. Usage: `node scripts/test-access-token.js <token> <project_id> [region]` |

## Project structure

```text
products/desktop/
├── apps/
│   ├── code/            # Electron desktop app (React, Vite)
│   ├── mobile/          # React Native mobile app (Expo)
│   └── web/             # Web host (cloud-only)
├── packages/
│   ├── agent/           # TypeScript agent framework
│   ├── core/            # Shared business logic
│   ├── ui/              # Shared React UI
│   ├── workspace-server/ # Local filesystem, git, and process services
│   └── platform/        # Host capability interfaces
└── docs/                 # Development and operational guides
```

## Documentation

| File | Description |
|------|-------------|
| [Documentation index](./docs/README.md) | Development, architecture, testing, operations, and feature guides |
| [Desktop app guide](./apps/code/README.md) | Building, signing, distribution, and workspace configuration |
| [Mobile app guide](./apps/mobile/README.md) | Expo setup, EAS builds, and TestFlight deployment |
| [Architecture and code rules](./AGENTS.md) | Source of truth for architecture, code style, and testing rules |
| [Contributing](./CONTRIBUTING.md) | How to contribute to PostHog Desktop |

## Contributing

We love contributions big and small. See [CONTRIBUTING.md](./CONTRIBUTING.md) to get started.
