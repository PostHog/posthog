# Architecture

Read [AGENTS.md](../AGENTS.md) first. This file documents implementation details.

## Layers

```text
apps/<host>
  boot, lifecycle, platform adapters, DI bindings
    |
    v
@posthog/ui
  React views, hooks, view-state stores, contributions
    |
    v
@posthog/core
  services, domain stores, domain schemas
    |
    v
@posthog/api-client              PostHog cloud HTTP API
@posthog/workspace-client        typed client for workspace-server
    |
    v
@posthog/workspace-server        Node capabilities: git, fs, pty, spawn, watchers

@posthog/platform                host-capability interfaces
@posthog/shared                  zero-dependency primitives
```

Host code boots and binds. Shared packages own reusable logic and UI. `core` and `ui` never import host transports.

Two tRPC surfaces exist:

- `@posthog/host-router`: Electron main process API for its renderer.
- `@posthog/workspace-server`: privileged Node backend API consumed by `@posthog/workspace-client`.

## Dependency Injection

Use plain Inversify through `@posthog/di`.

- Define an interface and `Symbol.for(...)` token in the owning package.
- Inject dependencies through constructors.
- Bind services in feature `ContainerModule`s.
- Load modules in host composition files.
- Call `setRootContainer(container)` before React service resolution.
- Use `bindToContainer((container) => ...)` for plain modules that register bindings before root initialization.
- Do not call `container.get(...)` or `resolveService(...)` inside services or components.

```ts
export const FOCUS_SERVICE = Symbol.for("posthog.core.focusService");

export interface IFocusService {
  enableFocus(input: EnableFocusInput): Promise<EnableFocusResult>;
}
```

```ts
@injectable()
export class FocusService implements IFocusService {
  constructor(
    @inject(GIT_SERVICE) private readonly git: IGitService,
    @inject(FOCUS_WORKSPACE_CLIENT) private readonly workspace: FocusWorkspaceClient,
  ) {}

  async enableFocus(input: EnableFocusInput): Promise<EnableFocusResult> {
    // orchestration
  }
}
```

```ts
export const focusCoreModule = new ContainerModule(({ bind }) => {
  bind(FOCUS_SERVICE).to(FocusService).inSingletonScope();
});
```

React resolves services only at boundaries:

```ts
const focus = useService(FOCUS_SERVICE);
```

Unit tests construct services with fakes instead of using the container.

## Contributions

Boot side effects are `Contribution`s:

- subscriptions
- routes
- commands
- menus
- feature initialization

Bind contributions in feature modules. `boot()` resolves and starts them before rendering.

```ts
bind(CONTRIBUTION).to(FileWatcherContribution).inSingletonScope();
```

```ts
setRootContainer(container);

import "./desktop-services";
import "./desktop-contributions";

await boot(container);
```

Components do not start long-lived subscriptions. A contribution starts the subscription, writes to a store, and components render store state.

## Host Router

`@posthog/host-router` is the Electron main-to-renderer API. Router files live at:

```text
packages/host-router/src/routers/<feature>.router.ts
```

Router rules:

- Import service tokens and schemas from the owning package.
- Resolve the service from `ctx.container`.
- Validate input with Zod.
- Forward to the service.
- Do not add business logic.

```ts
export const focusRouter = router({
  enableFocus: publicProcedure
    .input(enableFocusInput)
    .mutation(({ ctx, input }) =>
      ctx.container.get<IFocusService>(FOCUS_SERVICE).enableFocus(input)
    ),
});
```

The renderer imports `HostRouter` as a type and uses `useHostTRPC`. `trpcClient` remains in host glue under `apps/<host>`.

## Workspace Server

`@posthog/workspace-server` owns privileged Node work:

- git
- filesystem
- pty
- process spawn
- watchers

It exposes colocated tRPC routers. `@posthog/workspace-client` is the typed client. `core` services inject narrow workspace-client slices and call those procedures.

## Schemas

Use Zod at runtime boundaries. Infer TypeScript types from schemas.

```ts
export const getDataInput = z.object({
  id: z.string(),
});

export type GetDataInput = z.infer<typeof getDataInput>;
```

Use schemas for tRPC inputs/outputs, API boundary data, persisted data, and external tool payloads.

## Events

Use typed events for real-time push. Services may extend `TypedEventEmitter`. Routers expose streams as subscriptions.

```ts
@injectable()
export class FocusService extends TypedEventEmitter<FocusServiceEvents> {
  async checkout(input: CheckoutInput) {
    this.emit(FocusServiceEvent.Switched, { sessionId, branch });
  }
}
```

For per-instance streams, filter server-side by id.

## State

Store each fact once.

Domain state:

- lives in `@posthog/core`
- uses `zustand/vanilla`
- represents facts read by business logic

View state:

- lives in `@posthog/ui`
- uses React Zustand `create`
- represents selection, panel state, scroll position, drafts, and filters

Compute counts, labels, filtered lists, and status summaries from source facts.

## Adding a Feature

1. Choose the data source.
2. Add a `core` service when the feature has orchestration, retries, rules, sagas, or decisions.
3. Define Zod schemas in `schemas.ts`.
4. Define interface and token in `identifiers.ts`.
5. Bind the service in `<feature>.module.ts`.
6. Expose the service through host-router, or expose Node work through workspace-server.
7. Build UI in `packages/ui/src/features/<feature>/`.
8. Add hooks that each wrap one query, mutation, subscription, or selector.
9. Add a contribution for subscriptions, routes, commands, or feature boot.
10. Wire host adapters in `apps/<host>`.
11. Run `node scripts/check-host-boundaries.mjs`.

## MCP Apps

MCP Apps render tool-provided HTML UIs inside sandboxed iframes.

- Shared schemas: `@posthog/shared`.
- Service: `packages/core/src/mcp-apps/`.
- UI feature: `packages/ui/src/features/mcp-apps/`.
- Desktop host glue: `apps/code/src/renderer/features/mcp-apps/`.

The core service manages MCP server connections, caches resources, and proxies UI calls. `useAppBridge` handles `@modelcontextprotocol/ext-apps` host communication, tRPC routing, theme, display mode, and dimensions.

## References

- [AGENTS.md](../AGENTS.md)
- [conventions.md](./conventions.md)
- [testing.md](./testing.md)
