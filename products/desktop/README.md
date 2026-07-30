> [!IMPORTANT]
> Interested in the PostHog desktop app? [Join the waitlist](https://posthog.com/code) or hop into our [Discord](https://discord.gg/aSrHKVNVdR).

**[Download the latest version](https://github.com/PostHog/code/releases/latest)**

Found a bug or have feedback? [Open an issue](https://github.com/PostHog/code/issues/new) on GitHub.

# PostHog

This is the monorepo for the PostHog desktop and mobile apps and the agent framework that powers them.

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

### Running in Development

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

### Utility Scripts

Scripts in `scripts/` for development and debugging:

| Script | Description |
|--------|-------------|
| `scripts/clean-posthog-code-macos.sh` | Remove all PostHog app data from macOS (caches, preferences, logs, saved state). Use `--app` flag to also delete PostHog.app from /Applications. |
| `scripts/test-access-token.js` | Validate a PostHog OAuth access token by testing API endpoints. Usage: `node scripts/test-access-token.js <token> <project_id> [region]` |

## Project Structure

```
posthog-code/
├── apps/
│   ├── code/            # Electron desktop app (React, Vite)
│   ├── mobile/          # React Native mobile app (Expo)
│   └── cli/             # CLI for stacked PRs
├── packages/
│   ├── agent/           # TypeScript agent framework
│   ├── core/            # Shared business logic
│   ├── electron-trpc/   # tRPC for Electron IPC
│   └── shared/          # Shared utilities (Saga pattern, etc.)
```

## Documentation

| File | Description |
|------|-------------|
| [apps/code/README.md](./apps/code/README.md) | Desktop app: building, signing, distribution, and workspace configuration |
| [apps/mobile/README.md](./apps/mobile/README.md) | Mobile app: Expo setup, EAS builds, and TestFlight deployment |
| [apps/cli/README.md](./apps/cli/README.md) | CLI: stacked PR management with Jujutsu |
| [AGENTS.md](./AGENTS.md) | Architecture rules, code style, patterns, and testing guidelines (read by Claude Code, Codex, Cursor, Aider, etc.) |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | How to contribute to PostHog |
| [docs/LOCAL-DEVELOPMENT.md](./docs/LOCAL-DEVELOPMENT.md) | Connecting the desktop app to a local PostHog instance |
| [docs/UPDATES.md](./docs/UPDATES.md) | Release versioning and git tagging |
| [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md) | Common issues and fixes |
| [docs/DEEP-LINKS.md](./docs/DEEP-LINKS.md) | `posthog-code://` deep link schemes and parameters |

## Contributing

We love contributions big and small. See [CONTRIBUTING.md](./CONTRIBUTING.md) to get started.

## Troubleshooting

See [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md) for common issues (black screen, Electron install failures, native module crashes, Secretive commit signing, etc.).
