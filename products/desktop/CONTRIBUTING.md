# Contributing to PostHog

We love contributions big and small. The PostHog desktop app is the IDE for understanding how users interact with your product -- and we want the community involved in shaping it.

## Getting started

1. Fork the repo and clone it locally
2. Follow the [Development setup](#development-setup) below
3. Create a branch (`feat/my-change`, `fix/that-bug`)
4. Make your changes and open a pull request

Issues labeled [`good first issue`](https://github.com/PostHog/code/issues?q=sort%3Aupdated-desc%20is%3Aissue%20is%3Aopen%20label%3A%22good%20first%20issue%22) are a great place to start!

If an issue does not yet exist for your change, please create one first so we can align on the approach before you invest time.

## Development setup

```bash
# Prerequisites: Node.js 22+, pnpm 10.23+
pnpm install
cp .env.example .env
pnpm dev
```

See [docs/LOCAL-DEVELOPMENT.md](./docs/LOCAL-DEVELOPMENT.md) for connecting to a local PostHog instance.

## Before submitting

- Run `pnpm typecheck`, `pnpm lint` and `pnpm test` locally
- Resolve merge conflicts before requesting review
- Keep changes focused -- one logical change per PR
- Add tests where they meaningfully improve confidence
- Follow existing patterns and conventions in the areas you touch (see [AGENTS.md](./AGENTS.md) for architecture rules and code style)

## What to expect

- PRs are triaged and assigned to the relevant team
- Expect acknowledgement within a few days. Thorough reviews may take longer depending on load
- We sometimes close PRs that are out of scope or would add long-term maintenance burden. You're always welcome to reopen with updates

## Issues

Spotted a bug? Something broken? [Raise an issue](https://github.com/PostHog/code/issues/new) for the fastest response.

## Feature requests

Raise an issue and tag it as an enhancement. Give us as much context on the _why_ as possible -- we love hearing about the problem you're trying to solve.

If you're unsure whether something fits, open an issue first and we'll get back to you quickly.
