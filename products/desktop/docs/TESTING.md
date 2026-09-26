# Testing

## Commands

- `pnpm test`: run unit tests across packages.
  Turbo runs two packages at a time.
  Each Vitest process already uses every core, so turbo's default of ten packages at once starved the 4 core CI runner and made trivial tests hit their 5 second timeout.
- `pnpm --filter code test`: run desktop app unit tests.
- `pnpm test:e2e`: run Playwright E2E tests.
- `pnpm --filter <pkg> test`: run tests for one package.

## Live agent tests

Before running `pnpm --filter @posthog/agent test:e2e`, build its workspace dependencies with `pnpm exec turbo build --filter=@posthog/agent^...` from `products/desktop`.
This includes the harness extensions imported by the agent source.
Desktop CI uses the same dependency graph so new workspace dependencies are built before the live tests start.
The suite requires `POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY`, a reachable `POSTHOG_CODE_E2E_GATEWAY_URL`, and the bundled Codex binary.

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

## Comment Input Focus

In the right-panel comment input, click an empty area below the placeholder or
beside the send button. The editor must receive focus so you can type. Clicking
existing text must keep the selected caret position. Send and cancel buttons must
keep their own actions.

Run the focus and submission checks with:

```bash
pnpm --filter @posthog/ui test src/features/sessions/components/CommentComposer.integration.test.tsx
```

## Continue a completed report chat

Open a report whose linked cloud task has completed. In the chat, select
Advanced > Model and choose a model from another provider. Check that the
reasoning and permission controls match the selected model. Send a message.
The new run must use that model and retain the previous conversation.
An active run keeps the models supported by its current runtime.

## Composer text selection

In the new-session and session composers, select text and release the mouse outside the editor.
The selection must remain visible, including when you release over the surrounding padding.
A plain click on that padding must still focus the editor.
Buttons and menus must keep their own actions.

## Profile pictures

In Settings > Account, check a Gravatar with a transparent background. The picture must not show initials behind it.
Refresh the picture, close Settings, then open Settings again. The refreshed picture must remain visible without another refresh.
Other avatars for the same email must use the refreshed URL, including avatars at different sizes. Refresh state lasts until the app reloads.
The `Settings/AccountSettings` stories cover transparent pictures, missing pictures, and loading states.

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

PNGs are never committed. `desktop-storybook.yml` runs independently from the main Storybook workflow when Desktop code changes. It captures every Desktop story in Chromium and submits it as the `desktop-storybook` Visual Review run type. The first run after a repository registration marks the old signed baseline as new; approve it in Visual Review so the bot writes a baseline signed for this repository.

Run locally to debug a story (local PNGs are gitignored):

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
