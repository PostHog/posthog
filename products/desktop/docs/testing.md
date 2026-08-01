# Testing

## Commands

- `pnpm test`: run unit tests across packages.
- `pnpm --filter code test`: run desktop app unit tests.
- `pnpm test:e2e`: run Playwright E2E tests.
- `pnpm --filter <pkg> test`: run tests for one package.

## Test Types

Use unit tests when the code can run without Electron.

Unit-test:

- core services
- UI services
- Zustand stores
- pure utilities
- data transforms
- validators
- business decisions

Use E2E tests for behavior that needs the full app.

E2E-test:

- auth flows
- task creation
- workspace setup
- IPC behavior
- real Electron APIs
- multi-step user workflows
- regression coverage for reported app bugs

Rule: if Electron is not required, write a unit test.

## File Location

- Unit tests colocate with source as `.test.ts` or `.test.tsx`.
- E2E tests live in `tests/e2e/`.
- Package test setup files live at `<pkg>/src/test/setup.ts`.
- Feature-specific helpers colocate with the feature.

Avoid central test utility folders unless the helper is broadly reused across packages.

## Service Tests

Construct services with faked injected dependencies. Do not use the container unless the test is specifically about DI wiring.

```ts
const workspace = {
  focus: {
    enable: vi.fn().mockResolvedValue(ok),
  },
};

const git = {
  getCurrentBranch: vi.fn().mockResolvedValue("main"),
};

const service = new FocusService(
  git as unknown as IGitService,
  workspace as unknown as FocusWorkspaceClient
);

await service.enableFocus(input);

expect(workspace.focus.enable).toHaveBeenCalledWith(expectedInput);
```

Test the service decision, not the transport.

## Store Tests

Reset store state before each test. Clear storage when persistence is involved.

```ts
describe("store", () => {
  beforeEach(() => {
    localStorage.clear();
    useStore.setState({ open: false, width: 256 });
  });

  it("updates state", () => {
    useStore.getState().toggle();

    expect(useStore.getState().open).toBe(true);
  });

  it("persists selected fields", () => {
    useStore.getState().setOpen(true);

    const persisted = localStorage.getItem("store-key");

    expect(JSON.parse(persisted ?? "{}").state).toEqual({ open: true });
  });
});
```

## Parameterised Tests

Prefer a parameterised test shape when several cases exercise the same logic with different inputs and expectations. Use Vitest's `it.each` / `test.each` instead of copy-pasting near-identical `it` blocks.

```ts
it.each([
  { input: "main", expected: true },
  { input: "feature/x", expected: false },
  { input: "", expected: false },
])("isDefaultBranch($input) === $expected", ({ input, expected }) => {
  expect(isDefaultBranch(input)).toBe(expected);
});
```

Keep cases as separate `it` blocks when they differ in setup, assertions, or intent — parameterise repetition, not distinct behaviors.

## Mocking

Hoist mocks for modules that must be mocked before import evaluation.

```ts
const mockPty = vi.hoisted(() => ({
  spawn: vi.fn(),
}));

vi.mock("node-pty", () => mockPty);
```

Use simple module mocks for direct dependencies.

```ts
vi.mock("@utils/analytics", () => ({
  track: vi.fn(),
}));
```

Stub globals explicitly.

```ts
const mockFetch = vi.fn();

vi.stubGlobal("fetch", mockFetch);
mockFetch.mockResolvedValueOnce(ok());
```

## UI Tests

Prefer explicit props and fake services over app-wide setup. Test rendered behavior and user-observable state.

For components using DI:

- pass props directly when possible
- fake service interfaces
- bind only the services required by the component
- avoid running the full boot unless the test covers boot behavior

## E2E Tests

Use Playwright for flows that require the running app or Electron APIs.

Keep E2E tests focused:

- one user journey per test
- stable selectors
- no arbitrary sleeps
- assert visible outcomes
- capture regression conditions explicitly

## Interactive App Testing

To drive the **real running app** (live tRPC, workspace-server, real data) instead of writing a spec, use [agent-browser](https://github.com/vercel-labs/agent-browser) over the Chrome DevTools Protocol. The dev app already launches with `--remote-debugging-port=9222`, so an agent can connect, snapshot the accessibility tree, click/type and screenshot the live UI.

Two surfaces, pick by intent:

| Goal | Tool |
| --- | --- |
| Verify or screenshot a change in the real app, live data | agent-browser + CDP `:9222` (`test-electron-app` skill) |
| Regression coverage in CI | Playwright E2E (`tests/e2e/`) |

Workflow:

```bash
npm i -g agent-browser && agent-browser install   # once
pnpm dev                                            # run the app (exposes CDP on :9222)
pnpm app:cdp                                         # preflight + connect
agent-browser skills get electron                   # load the canonical commands
agent-browser snapshot -i                           # then click/type/screenshot
```

This drives whatever profile is signed into `~/.posthog-code`; do not mutate production data while exploring. See the `test-electron-app` skill.

## Storybook Visual Regression

Every story is screenshot in Chromium in both themes (`<story-id>--dark.png` and `--light.png`) using `@storybook/test-runner`, following posthog/posthog's setup. The harness lives in `apps/code/.storybook/test-runner.ts`.

PNGs are never committed. The `Storybook visual regression` workflow captures every story and submits the images to the [PostHog Visual Review product](https://us.posthog.com/project/2/visual_review) via the `vr` CLI (built from posthog/posthog). VR diffs against the signed hash manifest committed at `apps/code/snapshots.yml`, posts the result on the PR, and — once a human approves the changes in the VR UI — commits the updated manifest back to the PR branch. The next run then matches and goes green.

One-time setup (not yet done — the vr step no-ops until it is):

1. Register `PostHog/code` as a repo in Visual Review settings (project 2 on us.posthog.com); this mints the repo UUID.
2. Create a PostHog personal API key with the `visual_review` scope and store it as the `VR_API_TOKEN` Actions secret on this repo.
3. Commit the seeded baseline at `apps/code/snapshots.yml`:

   ```yaml
   version: 1
   config:
       api: https://us.posthog.com
       team: "2"
       repo: <uuid-from-step-1>
   snapshots: {}
   ```

Run locally to debug a story before pushing (local PNGs are gitignored):

```bash
pnpm --filter code build-storybook
cd apps/code && pnpm exec http-server storybook-static --port 6006 --silent &
pnpm --filter code test:visual:update    # capture; rerun with test:visual to spot local flakiness
```

Per-story control via story parameters (see the typing in `test-runner.ts`):

- `testOptions.viewport` — viewport size (default 1280x720)
- `testOptions.waitForSelector` — extra readiness selector(s)
- `testOptions.waitForLoadersToDisappear` — default `true`, waits out quill spinners/skeletons
- `testOptions.snapshotTargetSelector` — screenshot a specific element
- `testOptions.themes` — limit to `["dark"]` or `["light"]`
- `tags: ["test-skip"]` — skip snapshots for a story

Stories must render deterministically: the preview freezes the clock (`mockdate`) and seeds `Math.random` per render when running under the test runner, but story fixtures should still use fixed dates and stable data.

## Boundary Checks

After touching `@posthog/platform`, rebuild or typecheck its `dist/` before relying on downstream typechecks.

After touching `packages/core`, run:

```bash
biome lint packages/core
```

Expected result: zero `noRestrictedImports` violations.
