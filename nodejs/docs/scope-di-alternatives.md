# Could `Scope` be replaced by a TS DI framework?

Investigation summary. The conclusion up front: **no off-the-shelf TypeScript DI
library replaces `Scope` cleanly.** What we built is mostly a lifecycle
supervisor, not a dependency-injection container. The container portion of it
is trivial (one constructor call against a typed record); the hard parts —
ordered async start, reverse-order stop, partial-failure rollback, refcounted
boot of a shared root, and a state machine for concurrent start/stop — are
explicitly outside what DI libraries offer.

This document records what each candidate does, what it gives us, and why it
was rejected.

## Requirements `Scope` covers today

1. **Async per-service lifecycle.** Each entry exposes
   `start(): Promise<{ value, stop: () => Promise<void> }>`.
2. **Strict declaration-order start, reverse-order stop.**
3. **Partial-failure rollback during start.** If step 3 fails, steps 1–2 are
   torn down before the error is propagated.
4. **Refcounted boot across callers.** Shared infra (Postgres, Redis, producer
   registry) is owned by one root scope; multiple consumer scopes can call
   `start()` on it, only the first physically boots, only the last `stop()`
   tears down.
5. **State machine.** `Stopped → Starting → Started → Stopping → Stopped`. A
   start during `Stopping` waits; a stop during `Starting` waits.
6. **Nested scopes.** `parent.nest('child', (parentContainer, builder) => ...)`.
   Child sees parent's container as a fully typed input; child's container
   type is `Parent & Child`. Stopping the child releases its parent
   refcount.
7. **Type-safe container.** Inferred `Record<string, object>` — no string
   tokens, no class tokens, no `as` casts.
8. **No decorators / `reflect-metadata`.**
9. **Logging hooks** at every transition (start requested, per-entry
   start/stop, rollback, etc.).

These are characteristics of a *component / lifecycle* library, not a DI
container.

## Candidate libraries

### tsyringe (Microsoft)

**How it works.** Decorator-driven (`@injectable()`, `@inject('TOKEN')`). Uses
`reflect-metadata` to read constructor parameter types at runtime. Resolution
is by class or by string token. Bindings can be marked `singleton`,
`container-scoped`, `transient`, or `resolution-scoped`. Disposal is via the
`Disposable` interface; `container.dispose()` calls `dispose()` on
resolved instances.

**What we'd gain.** Standard Microsoft-blessed idiom; small.

**Why rejected.**

- Requires experimental decorators + `reflect-metadata` — we deliberately
  avoid these.
- No async constructors / factories — async startup must be done post-resolve
  or via factory shims, which defeats the point of the container.
- No documented teardown ordering.
- No refcount semantics across callers.
- No concurrency coordination.
- Resolution is token-based; we'd lose the inferred record type.

Covers maybe 10% of `Scope`. Ruled out on requirement 8 alone.

### InversifyJS

**How it works.** Decorator-first (`@injectable`, `@inject(TYPES.Foo)`) but
also supports `ContainerModule` for non-decorator bindings. Supports async
bindings via `.toDynamicValue(async () => ...)` and `container.getAsync<T>()`.
Each binding can have `onActivation` (post-resolve hook) and `onDeactivation`
(pre-unbind hook), both supporting async. `unbindAsync` /
`unbindAllAsync` tear things down. Parent/child containers exist.

**What we'd gain.** Mature, widely used, real async + deactivation hooks.

**Why rejected.**

- Still token-based; no inferred container type — every `container.get<Foo>(TYPES.Foo)`
  is an unchecked cast at the call site.
- No documented start/stop *ordering* — deactivation runs over the bindings in
  the order Inversify chooses, not declaration order or reverse-resolve order.
- No refcount: deactivating a binding tears it down regardless of whether
  another consumer is using it.
- No state machine for concurrent start/stop.
- Heavy ceremony — `TYPES` symbol files, decorators on every class.

Covers ~40% of `Scope`; we'd still hand-write ordering, rollback, refcount,
state machine, *and* lose container-type inference.

### awilix (jeffijoe)

**How it works.** No decorators. Register resolvers: `asValue`, `asFunction`,
`asClass`. `asFunction` supports promise-returning factories. Each registration
takes a `.disposer(fn)` callback. `container.dispose()` awaits every
disposer. `container.createScope()` creates a child container that inherits
from the parent. Types: `InferCradleFromContainer` / `InferCradleFromResolvers`
give a fully type-inferred `cradle` (no string-token cast at the call site).

**What we'd gain.** No decorators, type-inferred container, real async
factories, real disposer hooks, ordered disposal *of what was resolved during
this run*. The closest mainstream fit.

**Why rejected.**

- **No guaranteed teardown order.** Disposers fire in resolution order
  reversed, not declaration order — which means if a dep is lazy and
  resolved late, it tears down early. Our entries are eagerly started in a
  precise order; awilix's resolution-driven order isn't equivalent.
- **No rollback** if a factory in the middle of resolution throws — the
  partially-resolved cradle is left for the caller to clean up.
- **No refcount** across `container.dispose()` calls — once you dispose, the
  container is dead; we'd build our own "shared root + many consumers" layer
  on top.
- **No state machine** — concurrent `dispose` while a resolve is mid-flight
  is undefined.

Covers ~55% of `Scope`. We'd still write the refcount layer, the state
machine, eager ordered start, and the rollback. Net code saved: roughly
100 lines, in exchange for a third-party dep, a foreign mental model
(`cradle`), and the fact that the disposer-ordering semantics don't exactly
match what we want.

### iti (molszanski/iti)

**How it works.** No decorators, no tokens. `createContainer().add({ key: () => value })`
— the container's type is **fully inferred** from the keys. Native async
providers. `addDisposer({ key: (v) => ... })`. `container.disposeAll()` awaits
all registered disposers.

**What we'd gain.** Architecturally the closest type model to ours — the
container is literally an inferred `{ key: T, ... }` record, no token gymnastics.
Async factories first-class.

**Why rejected.**

- Same gaps as awilix: no eager ordered start, no rollback, no refcount, no
  state machine.
- Nesting doesn't compose two typed containers the way our
  `nest((parentContainer, builder) => ...)` does — parent containers exist
  but the child's resolved type doesn't carry the parent through.

Covers ~60% of `Scope`. Same conclusion as awilix — would save a bit of
container plumbing, doesn't touch the parts that are actually hard.

### typedi (typestack)

**How it works.** Decorator-driven (`@Service()`), `reflect-metadata`, similar
to tsyringe. Supports multiple named containers.

**Why rejected.** No async factories. No dispose hooks. No ordering. No
refcount. No type inference of the container shape. Strictly worse than
tsyringe for our use.

### diod (artberri)

**How it works.** ~2 kB. Decorator-driven autowiring. Transient / singleton /
per-request scopes for *resolution*.

**Why rejected.** Same gaps — no async, no dispose, no ordering, no refcount,
no container inference.

### brandi (vovaspace/brandi)

**How it works.** Token-based (`token<T>('name')`), no decorators, hierarchical
containers via `container.extend(parent)`. Synchronous only.

**Why rejected.** Synchronous-only is a non-starter. No dispose hooks, no
ordering, no refcount.

### NestJS

**How it works.** Framework. Modules expose providers; the runtime calls
`onModuleInit` / `onApplicationShutdown` hooks. Init order is topological;
async hooks are awaited.

**Why rejected.**

- It's a framework, not a library — adopting it for one ingestion service
  means buying into modules, decorators, the request-scoped DI machinery,
  controllers, the whole picture.
- **Async teardown ordering is an open bug** (nestjs/nest#14773): NestJS doesn't
  guarantee `onApplicationShutdown` fires in reverse-init order across async
  providers. That's exactly the property we rely on.
- No refcount across module instances.

Ruled out — framework adoption cost is huge and the one feature that would
attract us is broken.

### Effect-TS — `Layer` and `Scope`

**How it works.** Effect is a runtime + standard library for typed effectful
programming. `Layer<R, E, A>` describes how to build a service `A` from
requirements `R` with errors `E`; `Scope` is a first-class lifetime token
that runs registered finalizers on close. Layers compose (`Layer.merge`,
`Layer.provide`), finalizers run in reverse order, scopes are
reference-counted, the runtime coordinates concurrent acquire/release via
fibers. Decorator-free. Container type is the inferred `Context.Tag` set.

**What we'd gain.** Effect's `Layer` / `Scope` covers **all nine** of our
requirements natively. It's the only thing in the TS ecosystem that does.

**Why rejected.**

- Adopting Effect means adopting its runtime (`Effect.runPromise`,
  `Effect.gen`, the fiber model) across the consumer paths — every
  `start()` / `stop()` call site becomes effectful. That's a much larger
  change than this PR.
- Mental-model cost is real — nobody else in this codebase uses Effect.
- We don't get other Effect benefits unless we lean in further (typed
  errors, structured concurrency in the pipeline itself, etc.), so it'd be
  carrying a runtime for one module.

The right answer **if** we decide to adopt Effect repo-wide for ingestion;
the wrong answer for a one-off DI replacement.

## Why nothing fits

The "DI" we actually do is one line:
`new EventIngestionRestrictionManagerScope(container.postgres, container.redisPool)`.
A bare constructor against a typed record. No auto-wiring, no resolution
scopes, no factory injection, no decorator gymnastics. Everything a DI
container is built to solve, we don't have a problem with.

What we *do* have a problem with — ordered async startup, rollback,
refcounted shared infra, state machine, parent-typed nested scopes — is
*lifecycle graph* territory. In Java/Scala this is what `cats-effect.Resource`,
ZIO's `Scope`, or Spring's lifecycle interfaces handle. In TS, the only
library that ships the whole set is Effect.

If we adopted **awilix** or **iti** we'd shed maybe 100 lines of container
plumbing but still own ~370 lines of lifecycle code, plus pay for a foreign
type surface. Not worth it.

If we adopted **Effect** we'd shed all 470 lines but pay a runtime-adoption
cost across the ingestion service.

## Recommendation

Keep `service-registry.ts`. Revisit only if either of these becomes true:

- Ingestion adopts Effect-TS for other reasons → migrate `Scope` to
  `Layer` / `Scope`.
- A second consumer outside ingestion needs the same lifecycle pattern →
  extract `service-registry.ts` to a small internal package instead of
  pulling in awilix/iti, since the wrapper code would dominate anyway.
