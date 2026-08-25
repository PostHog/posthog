# PostHog Development Guide

`AGENTS.md` is the source of truth for architecture and development rules. `CLAUDE.md` is a symlink to this file. Edit this file only.

Feature-level guides follow the same convention: the content lives in `<dir>/AGENTS.md` with a `<dir>/CLAUDE.md` symlink beside it. When you add a new guide, add the symlink too (`ln -s AGENTS.md CLAUDE.md`).

## Architecture

PostHog uses a layered architecture. Business logic and UI live in shared `packages/*`. Each `apps/*` host boots those packages and binds host-specific implementations. `@posthog/core` and `@posthog/ui` must run unchanged on desktop, web, and mobile.

Principle: logic is portable; hosts are thin.

| Layer | Responsibility |
| --- | --- |
| `packages/core` | Host-agnostic business logic: orchestration, retries, dedupe, sagas, parsing, domain events, domain state. Inversify services only. No React, Node, Electron, or `trpcClient`. |
| `packages/workspace-server` | Node-only capabilities behind tRPC: git, fs, process spawn, pty, watchers. |
| `packages/ui` | React UI shell: views, components, hooks, view-state stores, route and command contributions. No business logic, Node, Electron, or `trpcClient`. |
| `apps/<host>` | Boot, lifecycle, platform adapters, DI wiring, host transports. No business logic. |

## Packages

| Package | Owns | Must not contain |
| --- | --- | --- |
| `@posthog/platform` | Host-capability interfaces and DI tokens. Host-neutral, zero runtime dependencies. | Implementations, Node, DOM, tRPC, Electron |
| `@posthog/shared` | Zero-dependency primitives, types, Saga pattern, cloud-prompt encoding. | Internal package imports, I/O |
| `@posthog/api-client` | PostHog/Django HTTPS client. Constructed by factory, not DI. | UI, Node-only host syscalls |
| `@posthog/workspace-client` | Thin tRPC client for local or sandbox workspace-server. Runs in any JS environment. | Business logic, UI |
| `@posthog/workspace-server` | Node backend services and colocated tRPC routers for git, fs, watchers, processes. | UI, core, Electron |
| `@posthog/core` | Portable Inversify services, domain schemas/types, domain stores (`zustand/vanilla`). Injects platform, workspace-client, api-client. | React, `trpcClient`, Node syscalls, Electron, host-router runtime |
| `@posthog/ui` | React components, hooks, contributions, view-state stores. Built on `@posthog/quill`. | Business logic, `trpcClient`, Node |
| `@posthog/host-trpc` | Shared `initTRPC` base with container-bearing context for Electron main routers. | Feature logic |
| `@posthog/host-router` | Electron host tRPC routers that resolve services from request context and forward calls. Exposes `HostRouter` type and renderer `useHostTRPC`. | Service implementations |
| `@posthog/di` | DI and boot primitives: `CONTRIBUTION`, `boot()`, `ROOT_LOGGER`, `setRootContainer()`, `bindToContainer()`, `useService`. | Feature code |
| `@posthog/electron-trpc` | tRPC-over-Electron-IPC transport. | Feature code |
| `@posthog/git`, `@posthog/enricher`, `@posthog/agent` | Reusable domain implementation packages. | Host-specific code |

Hosts:

- `apps/code`: Electron desktop host.
- `apps/web`: web host and portability smoke test.
- `apps/mobile`: React Native host.

## Rules

1. Business logic lives in `@posthog/core` services. Use `@injectable()` classes, constructor injection, and host-neutral dependencies.
2. Stores hold state only. No async flows, retries, dedupe, clients, cross-store orchestration, or business decisions.
3. Domain state lives in `@posthog/core` with `zustand/vanilla`. View state lives in `@posthog/ui` with `zustand`.
4. Node and host syscalls live in `@posthog/workspace-server` or a host adapter. `core` reaches workspace-server through an injected workspace-client slice.
5. Components render. Hooks wrap exactly one query, mutation, subscription, or store selector. Multi-source orchestration belongs in a service method.
6. Cross-feature coordination uses a service or `Contribution` emitting typed events. Stores do not reach into other stores.
7. Runtime boundary shapes use Zod schemas in `schemas.ts`. Infer TypeScript types from schemas.
8. Host capabilities use `@posthog/platform` interfaces plus per-host adapters under `apps/<host>`.
9. Use constructor injection only. Do not use `container.get(...)` or `resolveService(...)` inside service methods or components. `resolveService` is allowed only in host composition seams under `apps/`.
10. Boot side effects are `Contribution`s bound in feature modules and started by `boot()`.
11. tRPC routers are one-line forwards over services. No inline business logic.
12. Use Inversify with `@inversifyjs/strongly-typed`. Define each token as a standalone `export const TOKEN = Symbol.for("posthog.<area>.<thing>")` beside its `interface`/service — never an object-literal token bag (`TOKENS = { X: Symbol.for(...) }`), because object properties are not `unique symbol` and cannot key a binding map. Every composition root declares a `BindingMap` interface (token → bound type) and constructs `new TypedContainer<BindingMap>()`, so a mistyped bind or a resolve of an unbound token fails at compile time. Bind in the feature module. Do not use `@provide` or `*Port` naming.
13. Use `@posthog/quill` for rendering-layer primitives. Never import Radix — see [UI Components](#ui-components). Routing is TanStack Router contributed per feature.

Hard boundary: `@posthog/core` and `@posthog/ui` never import host transports. No `trpcClient`, `electron`, or `node:*`.

Hard boundary: no new `@radix-ui/*` imports anywhere in the repo.

## Import Direction

Enforced by Biome `noRestrictedImports`.

- `platform` and `shared` import no internal packages.
- `api-client` and `workspace-client` may import `shared` and relevant `platform` contracts. No UI or Node host syscalls.
- `workspace-server` may import `shared`, `platform` contracts, Node modules, and workspace-server code. Never `core` or `ui`.
- `core` may import `shared`, `platform`, `workspace-client`, `api-client`, and other core code. Never `ui`, `workspace-server`, `electron`, `node:*`, `trpcClient`, or host-router runtime.
- `ui` may import `core`, `platform`, `shared`, `@posthog/quill`, and UI feature public files. Never `workspace-server`, `electron`, `node:*`, or `trpcClient`.
- `apps/<host>` may import any package and its own host adapters.

## Core Eligibility

`core` is portable business logic. If code touches the host, it is not core yet.

| Host dependency | Correct home |
| --- | --- |
| `node:fs`, `node:path`, `node:child_process`, `process.*` | `workspace-server`, or an injected platform/environment interface |
| `node:crypto` for ids, hashes, PKCE, random | injected platform crypto/random interface |
| `node:events` emitters or async iterators | shared event abstraction, or keep source in `workspace-server` |
| `@posthog/enricher`, git/file/AST repo scans | `workspace-server` owns the scan; `core` owns result decisions |
| `process.platform`, `process.arch` | typed host-info interface supplied by host |

Split host-tangled algorithms: pure decision in `core`, host access in `workspace-server` or a platform adapter.

## Placement Decision

For each new file or meaningful change:

1. Data source:
   - Git, fs, process, pty, watchers: `workspace-server` procedure, consumed by a `core` service through workspace-client.
   - PostHog cloud API: `core` service/function using `@posthog/api-client`.
   - Client-local host capability: `@posthog/platform` interface plus per-host adapter.
2. Logic:
   - Real orchestration, retries, rules, sagas, or decisions: `core` service.
   - Trivial passthrough or streamed value: store plus host glue.
3. State:
   - Domain fact read by business logic: core store.
   - Pure view state: UI store.

## Forbidden Patterns

- Any new `@radix-ui/*` import (`@radix-ui/themes`, `@radix-ui/react-*`). Use `@posthog/quill` plus `div` + Tailwind.
- Radix layout primitives (`Box`, `Flex`, `Grid`, `Section`, `Container`) in code you touch; replace them with `div`s.
- Business logic in store actions.
- Domain stores in `@posthog/ui`.
- `trpcClient` imports in `@posthog/core` or `@posthog/ui`.
- Service-locator calls inside services or components.
- Hooks that orchestrate multiple queries.
- Platform interfaces for backend data.
- Services for trivial passthroughs.
- Business logic in platform adapters.
- tRPC routers with inline logic or no backing service.
- Object-literal DI token bags (`TOKENS = { X: Symbol.for(...) }`); use standalone token consts so a `BindingMap` can key on them.
- Untyped `new Container()` at a composition root; use `new TypedContainer<BindingMap>()`.
- Bespoke clients that wrap `trpcClient.x` one-to-one.
- `*Port`, `*_PORT`, or `ports.ts` naming.
- Business logic in `apps/<host>`.
- New ad-hoc broad in-app announcement or promo surfaces (flag-gated promo cards, dismissible banners, one-time modals). Broad announcements are remotely controlled via the `posthog-desktop-announcements` flag payload — see [docs/ANNOUNCEMENTS.md](./docs/ANNOUNCEMENTS.md).

## Host Boundary

`apps/code` contains Electron boot, lifecycle, platform adapters, and DI wiring only. `scripts/check-host-boundaries.mjs` checks host thinness against `scripts/host-boundary-allowlist.json`.

When moving logic out of `apps/code`, run:

```bash
node scripts/check-host-boundaries.mjs --prune
```

Do not use `--init` to baseline new violations.

## Web Host

`apps/web` is a real host and the portability smoke test: if a `@posthog/core`/`@posthog/ui` change compiles and boots on desktop but not here, it leaked a host dependency. It is **cloud-only** — no local filesystem, git, pty, or worktrees — so it binds `HOST_CAPABILITIES` to `{ localWorkspaces: false }` and stubs local-only host clients to reject at call time.

Building a feature for web means: the portable core/UI already runs unchanged; you only supply web adapters and bind them.

- **Composition root** is `apps/web/src/web-container.ts` (`WebBindings` + `TypedContainer<WebBindings>`). It loads the same core/UI feature modules `apps/code`'s renderer does, then binds web adapters (the `web-*.ts` files) for each platform/host capability. Unlike desktop, module-loading and adapter-binding live in this one file, not split into `desktop-contributions.ts` / `desktop-services.ts`.
- **Transport** is the entire desktop↔web difference. `web-trpc.ts` builds `HOST_TRPC_CLIENT` from an in-process `unstable_localLink` over `web-host-router.ts` (a subset of `HostRouter`, same procedure shapes) instead of Electron's `ipcLink` — no HTTP hop; the backing services are host-agnostic core code resolved from the root container per call. Both hosts use the `superjson` transformer; keep them in sync (the host-trpc base sets `transformer: superjson`).
- **New host capability?** Add a `@posthog/platform` interface (host-neutral) and a web adapter under `apps/web/src`, then bind it in `web-container.ts`. If the shared app resolves it eagerly at `__root` via `useService`, an unbound token crashes the tree — `assertHostCapabilities(container, REQUIRED_HOST_CAPABILITIES)` at the end of `web-container.ts` catches that at boot instead of on first navigation.
- **Persistence.** localStorage is the web host's single persistence layer; route all access through `web-local-store.ts` — `createRecordStore(key, entrySchema)` for the per-device `Record<string, Entry>` registries, `readValidated(key, schema, fallback)` for a single persisted object, the raw `readJson`/`writeJson`/`removeKey` primitives for anything without a schema, and `rawLocalStorage` for the zustand backend. Do not call `window.localStorage` directly. Persisted stores are discardable per-device caches validated against a Zod schema on read (invalid data is dropped and rebuilt), so evolving a shape is a schema edit, not a hand-written migration. IndexedDB is reserved for exactly one thing — the non-extractable auth cipher key in `web-auth-adapters.ts` — because localStorage cannot hold a `CryptoKey` without exposing its raw bytes; do not add other IndexedDB usage or move that key to localStorage.
- **Boot** is `main.tsx`: import `./web-storage` first (registers the persistence backend before stores construct), then the container, `setRootContainer`, `boot()`.
- **Commands.** `pnpm --filter @posthog/web dev` (Vite dev server), `build`, `typecheck`. E2E: `pnpm --filter @posthog/web test:e2e` (Playwright, `tests/e2e/`). There is no Vitest unit suite in `apps/web`.

## Structure

```text
apps/code/src/
|-- main/
|   |-- index.ts                 # composition root
|   |-- bootstrap.ts             # boot sequence
|   |-- window.ts, menu.ts, deep-links.ts, preload.ts
|   |-- di/                      # container and host tokens
|   |-- services/                # host-resident services
|   `-- platform-adapters/       # Electron adapters
`-- renderer/
    |-- main.tsx                 # imports wiring, boots the app
    |-- desktop-services.ts      # renderer host adapter bindings
    |-- desktop-contributions.ts # loads core/ui modules
    |-- platform-adapters/       # renderer adapters wrapping host transport
    |-- features/                # host glue only
    `-- trpc/client.ts           # renderer trpcClient for host glue
```

```text
packages/core/src/<feature>/
|-- <feature>.ts
|-- <feature>.module.ts
|-- <feature>Store.ts
|-- identifiers.ts
|-- schemas.ts
`-- <feature>.test.ts

packages/host-router/src/routers/<feature>.router.ts

packages/ui/src/features/<feature>/
|-- <Feature>View.tsx
|-- <feature>.contribution.ts
|-- <feature>.module.ts
|-- store.ts
`-- use<Feature>.ts
```

## DI and Boot

- Tokens are standalone `export const TOKEN = Symbol.for("posthog.<area>.<thing>")` consts, defined beside the interface in the owning package. Standalone consts infer `unique symbol`, which is what lets a `BindingMap` key on them; object-literal token bags do not and are forbidden.
- Each composition root (`apps/code` main + renderer, `apps/web`, `packages/workspace-server`) owns a `BindingMap` interface mapping every token it binds to the bound type, and constructs `new TypedContainer<BindingMap>()` (from `@inversifyjs/strongly-typed`). `bind`/`get`/`isBound` are then checked against the map at compile time.
- Services bind in feature `.module.ts` files with `ContainerModule` (typed via `TypedContainerModule<BindingMap>` where the root is typed).
- Hosts load modules in `desktop-contributions.ts` or the equivalent web/mobile composition file.
- Hosts bind platform implementations in `desktop-services.ts`, `main/index.ts`, or host equivalents.
- Hosts call `setRootContainer(container)` before resolving services through React or host seams.
- Plain modules that must register bindings before root initialization use `bindToContainer((container) => ...)`.
- `CONTRIBUTION` starts subscriptions, commands, routes, menus, and feature boot.
- React uses `useService(TOKEN)` at boundaries only.

```ts
setRootContainer(container);

import "./desktop-services";
import "./desktop-contributions";

await boot(container);
```

## Commands

- `pnpm install`: install dependencies.
- `pnpm bootstrap:cloud-task`: link dependencies from the prebaked pnpm store without running unrelated app install hooks, then build the packages required before scoped typechecks in cloud tasks.
- `pnpm dev`: run agent watch and desktop app.
- `pnpm build`: build all packages.
- `pnpm typecheck`: typecheck all packages.
- `pnpm lint`: run Biome lint and autofix.
- `pnpm format`: run Biome format.
- `pnpm test`: run unit tests.
- `pnpm test:e2e`: run Playwright tests.
- `pnpm --filter <pkg> typecheck|test|build`: run a scoped task.
- `pnpm --filter code package|make`: package the Electron app.
- `node scripts/check-host-boundaries.mjs`: verify host boundary allowlist.
- `node scripts/check-mobile-types.mjs`: typecheck `apps/mobile` against its error baseline.

## Mobile Host Types

`apps/mobile` typechecks against a baseline of pre-existing errors, not against zero.
`pnpm typecheck` runs it like every other package; `scripts/check-mobile-types.mjs` fails only on errors absent from `scripts/mobile-type-baseline.json`.

Metro strips types instead of checking them, so before this the mobile host was the one place a shared-package change could break without CI noticing — a new method on a `@posthog/platform` interface, a renamed `@posthog/core` export.

After fixing baselined errors, shrink the baseline:

```bash
node scripts/check-mobile-types.mjs --prune
```

Do not use `--init` to baseline new errors.

## UI Components

**Radix is banned. Do not add a `@radix-ui/*` import to any file, ever.** That covers
`@radix-ui/themes` and every `@radix-ui/react-*` package. There is no "just this once"
exception for matching surrounding code: the ~500 files that still import Radix are
legacy awaiting migration, not a pattern to copy. If a file you are editing already
imports Radix, that is a reason to remove those imports, not to add more.

Rendering primitives come from `@posthog/quill`. Layout comes from plain HTML elements
plus Tailwind.

### Replace Radix as you go

When you touch a component that imports Radix, migrate the parts you are working in.
Swap the whole file when the file is small or the change is broad; otherwise migrate at
least the elements your diff touches, and leave the file no more Radix-dependent than
you found it. Don't open a drive-by migration of an untouched file in an unrelated PR.

Layout primitives become `div`s (or the right semantic element) with Tailwind classes:

| Radix Themes | Replace with |
| --- | --- |
| `<Box p="2">` | `<div className="p-2">` |
| `<Flex align="center" gap="2">` | `<div className="flex items-center gap-2">` |
| `<Flex direction="column">` | `<div className="flex flex-col">` |
| `<Grid columns="2" gap="3">` | `<div className="grid grid-cols-2 gap-3">` |
| `<Section>`, `<Container>` | `<div>` / `<section>` + Tailwind |
| `<ScrollArea>` | `<div className="overflow-y-auto">` |
| `<Heading>` | quill `Heading`, or `<h1>`–`<h6>` + Tailwind |
| `<Code>`, `<Blockquote>` | `<code>`, `<blockquote>` + Tailwind |
| `<VisuallyHidden>` | `className="sr-only"` |
| `<Link>` | TanStack Router `Link` (in quill, `render={<Link … />}`) |

Everything else has a quill equivalent — import it from `@posthog/quill`:

| Radix Themes | quill |
| --- | --- |
| `Text` | `Text` |
| `Button`, `IconButton` | `Button` (`variant`/`size` props) |
| `TextField`, `TextArea` | `Input`, `Textarea`, `InputGroup*` |
| `Select`, `Checkbox`, `Switch`, `Slider`, `Progress` | same names |
| `SegmentedControl`, `RadioGroup` | `ToggleGroup` + `ToggleGroupItem`, or `Tabs` |
| `Badge`, `Avatar`, `Separator`, `Skeleton`, `Spinner`, `Kbd`, `Card`, `Table*`, `Tabs*` | same names |
| `Tooltip`, `Popover`, `Dialog`, `AlertDialog`, `DropdownMenu`, `ContextMenu` | same names, as `*Trigger` / `*Content` compounds |
| `Callout` | compose a `div` with Tailwind, or quill `Item*` |

No quill equivalent and no plain-HTML answer? Build it from HTML + Tailwind in the
feature, or add it to quill (see [`.claude/skills/quill-code/SKILL.md`](./.claude/skills/quill-code/SKILL.md)).
Pulling in a Radix package is not the fallback.

### The two carve-outs

- **CSS variables are not components.** Tailwind classes like `text-(--gray-12)`,
  `bg-(--gray-2)`, and `rounded-(--radius-2)` come from Radix's *CSS token* layer and
  stay. Keep using them; do not "de-Radix" a stylesheet.
- **The `<Theme>` root stays for now.** The app-level provider (`Providers.tsx`,
  `.storybook/preview.tsx`) and the `<Theme>` wrapper in existing tests supply those
  tokens. Leave them alone — removing them is a separate migration. Do not add
  `<Theme>` to new files; new tests should not need it.

## Code Style

- Prefer local code over new dependencies for simple fixes.
- Keep functions focused.
- Use Biome, not ESLint or Prettier. Use 2-space indentation and double quotes.
- No `console.*` in source. Inject `ROOT_LOGGER` as `RootLogger` and call `.scope(name)`. Logger files are exempt.
- TypeScript strict mode. Use explicit types where they clarify public contracts or nontrivial values.
- Use path aliases and package public exports. Avoid deep relative imports.
- No barrel files (`index.ts`).
- Use Tailwind first. Keep classes sorted. Use inline `style` only for runtime values, library configuration, or CSS variables.
- Empty/placeholder/loading screens (canvas and elsewhere) are a `@posthog/quill` `<Empty>` (`EmptyHeader` → `EmptyMedia variant="icon"` → `EmptyTitle` → `EmptyDescription`, then `EmptyContent` for CTAs). Don't hand-roll the centered Flex + dashed icon box. CTAs are quill `Button`s: primary action `variant="primary"`, secondary `variant="outline"`, `size="default"`. For a link CTA use `render={<Link … />}` (Base UI), not `asChild`.
- Abort controllers before awaiting cleanup that depends on them.

See [docs/CONVENTIONS.md](./docs/CONVENTIONS.md).

## Agent Integration

- Use SDK types from `@anthropic-ai/claude-agent-sdk` and `@agentclientprotocol/sdk`.
- Do not use Claude Code SDK `rawInput`. Use Zod-validated metadata.
- User approvals are tool calls with permissions. Do not model approvals as custom methods plus notifications.

## Key Libraries

- React 19, Tailwind CSS, `@posthog/quill` (the component library — Radix is banned in new code, see [UI Components](#ui-components); Radix Themes remains only as the CSS-token layer and legacy imports pending migration)
- TanStack Query, TanStack Router
- Zustand, InversifyJS (with `@inversifyjs/strongly-typed`), Zod
- xterm.js, CodeMirror, Tiptap

## Testing

- Unit tests: Vitest.
- E2E tests: Playwright.
- Test core/UI services and stores with faked injected dependencies and explicit props.
- Prefer a parameterised test shape (`it.each`/`test.each`) when several cases exercise the same logic with different inputs and expectations. Keep separate tests when cases differ in setup, assertions, or intent.
- Colocate tests as `.test.ts` or `.test.tsx`.
- Put E2E tests in `tests/e2e/`.
- Drive and screenshot the real running app (live data) with agent-browser over CDP `:9222`: run `pnpm app:cdp` or use the `test-electron-app` skill.
- Treat virtualized-list overscan as a performance setting, not a scroll-correctness fix; preserve the visible anchor when measured row heights change.
- After touching `@posthog/platform`, rebuild or typecheck its `dist/`.
- After touching `packages/core`, run `biome lint packages/core` and verify zero `noRestrictedImports`.

See [docs/TESTING.md](./docs/TESTING.md).

## Reference

- [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)
- [docs/CONVENTIONS.md](./docs/CONVENTIONS.md)
- [docs/TESTING.md](./docs/TESTING.md)
- [docs/ANNOUNCEMENTS.md](./docs/ANNOUNCEMENTS.md)
- [docs/DEEP-LINKS.md](./docs/DEEP-LINKS.md)
- [docs/LOCAL-DEVELOPMENT.md](./docs/LOCAL-DEVELOPMENT.md)
- [docs/UPDATES.md](./docs/UPDATES.md)
- [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md)
