# Testing kea logics

PostHog tests kea logics with [`kea-test-utils`](https://github.com/keajs/kea-test-utils)
plus jest, MSW for HTTP, and a small `initKeaTests` helper.

## Setup boilerplate

```ts
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { fooLogic } from './fooLogic'

describe('fooLogic', () => {
  let logic: ReturnType<typeof fooLogic.build>

  beforeEach(() => {
    useMocks({
      get: {
        '/api/projects/:team_id/foos/:id/': (req) => [200, { id: req.params.id, name: 'hello' }],
      },
      post: { '/api/projects/:team_id/foos/': { id: 'new', name: 'new' } },
    })
    initKeaTests()
    logic = fooLogic({ fooId: '123' })
    logic.mount()
  })

  afterEach(() => {
    logic.unmount()
  })
})
```

- `initKeaTests()` (in `frontend/src/test/init.ts`) calls `initKea` with an in-memory
  history and mounts the common logics (`preflightLogic`, `teamLogic`, `projectLogic`,
  `organizationLogic`). Pass `mountCommonLogic = false` only if your test needs to
  control those manually.
- `useMocks(...)` (in `frontend/src/mocks/jest.ts`) is the MSW handler registration. The
  matcher supports path parameters and HTTP methods. Unhandled requests log a warning.
- `ReturnType<typeof fooLogic.build>` is the conventional way to type the local variable
  for both keyed and unkeyed logics.

## `expectLogic` assertions

```ts
// Synchronous dispatch
expectLogic(logic, () => {
  logic.actions.setName('hi')
})
  .toDispatchActions(['setName'])
  .toMatchValues({ name: 'hi' })

// Async — await the whole expectation
await expectLogic(logic, () => {
  logic.actions.loadFoo()
})
  .toFinishAllListeners()
  .toMatchValues({
    foo: { id: '123', name: 'hello' },
    fooLoading: false,
  })

// Assert an action did NOT fire
await expectLogic(logic, () => {
  logic.actions.setQuery(logic.values.query) // same value, should be a no-op
}).toNotHaveDispatchedActions(['loadResults'])

// Router-driven action
import { router } from 'kea-router'

router.actions.push('/foos/123')
expectLogic(logic).toDispatchActions(['setFooId']).toMatchValues({ fooId: '123' })
```

Common assertion methods from `kea-test-utils`:

| Method                                | Use                                                           |
| ------------------------------------- | ------------------------------------------------------------- |
| `.toDispatchActions([...])`           | Actions fired in order (other actions may interleave).        |
| `.toDispatchActionsInAnyOrder([...])` | Actions fired but order doesn't matter.                       |
| `.toNotHaveDispatchedActions([...])`  | None of the listed actions fired.                             |
| `.toMatchValues({ key: value })`      | Reducer/selector values match (partial matching for objects). |
| `.toFinishAllListeners(timeoutMs?)`   | Awaits all in-flight async listeners.                         |
| `.toFinishListener(actionName)`       | Awaits a specific listener.                                   |
| `partial({ ... })` / `truth(fn)`      | Helpers for value matching.                                   |

## Parameterise

Per repo convention ([CLAUDE.md](../../../../CLAUDE.md)), parameterise variations of the
same shape rather than copy-pasting describe bodies:

```ts
describe.each([
  ['draft', 'editFoo', { editing: true }],
  ['saved', 'saveFoo', { editing: false }],
])('after %s', (_, action, expectedValues) => {
  it('updates editing state', async () => {
    await expectLogic(logic, () => {
      logic.actions[action]()
    })
      .toFinishAllListeners()
      .toMatchValues(expectedValues)
  })
})
```

## Mocking non-HTTP async work

For loaders backed by code that isn't an HTTP call (e.g. `performQuery`,
`api.foos.bar` helpers that wrap multiple calls), use `jest.mock` at the top of the
file — jest hoists these above imports:

```ts
jest.mock('~/queries/query', () => ({
  __esModule: true,
  ...jest.requireActual('~/queries/query'),
  performQuery: jest.fn().mockResolvedValue({ result: [] }),
}))
```

## Intentional loader failures

If you're testing a loader's failure path, the global `onFailure` toast will fire and
spam console errors. Silence it for the test:

```ts
import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'

beforeEach(() => silenceKeaLoadersErrors())
afterEach(() => resumeKeaLoadersErrors())
```

## Keyed logics

```ts
logic = fooLogic({ fooId: '123' })
logic.mount()

expect(logic.key).toEqual('123')

// Asserting required props throw on missing key
it('requires fooId', () => {
  expect(() => fooLogic()).toThrow(/must init/i)
})
```

## What not to do

- **Don't share a single `logic` instance across `describe` blocks** — kea's redux store
  is reset by `initKeaTests()` per `beforeEach`. Build and mount inside `beforeEach`.
- **Don't `await` plain action calls** — actions are synchronous dispatches. Await
  `expectLogic(...).toFinishAllListeners()` instead.
- **Don't rely on real HTTP** — every loader hit must be mocked via `useMocks`,
  otherwise MSW warns and your test depends on the dev server being up.

## Finding examples in the wild

For each pattern (form logic test, loader test with `toFinishAllListeners`, keyed
logic with `useMocks`, router-driven test with `urlToAction` assertions), grep for
the relevant builder or matcher inside `**/*.test.ts` — there are plenty of
current examples and the conventions are stable.
