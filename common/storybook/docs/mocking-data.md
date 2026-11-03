# Mocking data in stories

Stories talk to the PostHog API through a Mock Service Worker that starts in `preview.tsx`.
Every request goes to the worker first: a story mock, then a default mock, then the network.

## Mock API responses

Two helpers in `frontend/src/mocks/browser.tsx` add mocks for one story:

| Helper                     | Where it goes                                    | Use it when                                                    |
| -------------------------- | ------------------------------------------------ | -------------------------------------------------------------- |
| `mswDecorator(mocks)`      | `decorators: [...]` on the meta or on a story    | The mocks are fixed for the story. This is the usual choice.   |
| `useStorybookMocks(mocks)` | Inside `render`, a story function or a decorator | The mocks depend on `args` or on other values built in render. |

```ts
decorators: [
  mswDecorator({
    get: {
      '/api/environments/:team_id/insights/': toPaginatedResponse([insight]),
      '/api/environments/:team_id/insights/:id/': ({ params }) => insightsById[params.id as string],
    },
    post: {
      '/api/environments/:team_id/query/': async ({ request }) => {
        const body = await request.json()
        return body.query.kind === 'TrendsQuery' ? trendsResult : [400, { detail: 'Unexpected query' }]
      },
    },
    delete: { '/api/environments/:team_id/insights/:id/': [204] },
  }),
]
```

- The methods are `get`, `post`, `put`, `patch`, `delete` and `options`. Paths use MSW syntax: `:param` matches one segment.
- `mswDecorator` adds a trailing slash to every path, so a default mock with a slash can't shadow a story mock without one.
- Story mocks go before the defaults, so a story mock always wins.
- `mswDecorator` also reads `parameters.msw.mocks`, and its own argument wins over them. `parameters.msw.mocks` does nothing without `mswDecorator` on the story or meta.
- A meta `mswDecorator` and a story `mswDecorator` both apply. The story's decorator runs last, so its mocks win for the same path.
- `worker.resetHandlers()` runs before each story, so no mock carries over to the next one.

### What a mock returns

| The mock returns                                 | The response                                                    |
| ------------------------------------------------ | --------------------------------------------------------------- |
| An object, an array or any other JSON value      | That value as a JSON body, status 200                           |
| `[status, body]`                                 | That body with that status                                      |
| `[status]`                                       | An empty body with that status                                  |
| A `Response` or an MSW `HttpResponse`            | That response, as is                                            |
| `undefined` or `null`                            | An empty 200                                                    |
| A function `({ request, params, cookies }) => …` | Whatever the function returns, from this list. It can be async. |

- An empty 200 is not a network error. Return `HttpResponse.error()` to model a failed request.
- A request that never answers keeps a loader on screen: `() => new Promise(() => {})`. Set `testOptions.waitForLoadersToDisappear: false` and wait for the loading state with `waitForSelector`, or the story times out.
- `toPaginatedResponse(results)` and `EMPTY_PAGINATED_RESPONSE` from `~/mocks/handlers` build a DRF page.

### `environments` and `projects` paths

`/api/environments/` is an alias of `/api/projects/` on the backend.
A mock on an `/api/environments/...` path also answers the same `/api/projects/...` path, unless a mock already covers that one.
The alias goes one way only: a `/api/projects/...` mock never answers an `/api/environments/...` request.

### Requests nobody mocks

The worker logs a warning and lets the request through to the network. Locally that is the Storybook server, in CI the static build, so the request fails or returns HTML.
That can resolve after the snapshot and change it. Mock every request the story makes.
Look for `[MSW] Warning: intercepted a request without a matching request handler` in the browser console to find them.

## Default mocks

`frontend/src/mocks/handlers.ts` answers the requests most scenes make on load, so a story mocks only what it shows. Among them:

- `/api/users/@me/`, `/api/organizations/@current/`, `/api/environments/@current/` and `/api/projects/@current/` return the default user, organization, team and project.
- `/_preflight` returns `frontend/src/mocks/fixtures/_preflight.json`: not cloud, debug on, region US, `site_url` `http://localhost:6006`.
- Many common lists return empty pages, for example dashboards, actions, feature flags and experiments. Cohorts return one default cohort.
- `POST /api/environments/:team_id/query/` returns `{ results: [] }`.
- The posthog-js endpoints answer `ok`, so the app's own analytics never reach a real host.
- Requests that would add a banner that changes over time return a quiet answer: the posthog-js release check returns no tags, and the proxy check returns a working proxy.
- The sidebar starts with four starred products, so a scene story doesn't show the whole product catalog.

Read `handlers.ts` before you mock a path. A default may already return what you need, and your mock replaces it for the whole story.

## The app context every story starts with

`common/storybook/.storybook/app-context.ts` sets `window.POSTHOG_APP_CONTEXT`:

- `current_team` is `MOCK_DEFAULT_TEAM`, and `current_project` is `MOCK_DEFAULT_PROJECT`, both from `lib/api.mock`.
- `current_user` and `preflight` are empty, so the app fetches `/api/users/@me/` and `/_preflight`, and the default mocks answer.
- `persisted_feature_flags` holds the story's `featureFlags`.
- `resource_access_control` gives `manager` access to everything except the activity log and the toolbar, which are `viewer`.

To change the user, the organization or the preflight, mock its endpoint with a copy of the default:

```ts
import { MOCK_DEFAULT_USER } from 'lib/api.mock'

mswDecorator({ get: { '/api/users/@me/': { ...MOCK_DEFAULT_USER, is_staff: true } } })
```

The team and the project work differently.
`teamLogic` and `projectLogic` take them from the app context when they mount and never request them, so a mock of their endpoint changes nothing.
Set them after mount instead, with `teamLogic.actions.loadCurrentTeamSuccess` or `projectLogic.actions.loadCurrentProjectSuccess`:

```tsx
render: () => {
    const { loadCurrentTeamSuccess } = useActions(teamLogic)
    useDelayedOnMountEffect(() => {
        loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, created_at: '2023-05-23T00:00:00Z' })
    })
    return <App />
},
```

`OnboardingWelcome.stories.tsx` uses this pattern. `withKea` remounts the logics for the next story, so nothing carries over.

`lib/api.mock.ts` holds `MOCK_DEFAULT_USER`, `MOCK_DEFAULT_TEAM`, `MOCK_DEFAULT_ORGANIZATION`, `MOCK_TEAM_ID` and the other defaults. `frontend/src/mocks/fixtures/` holds larger JSON fixtures.

## Plan features: `useAvailableFeatures`

```ts
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'

export const WithAdvancedPermissions: Story = {
    render: () => {
        useAvailableFeatures([AvailableFeature.ADVANCED_PERMISSIONS])
        return <MyComponent />
    },
}
```

- The default user and organization mocks return these features as `available_product_features`, so paywalled UI unlocks.
- `withKea` resets the list to none before each story. The list is module state, so set it in every story that needs it, not once in a shared helper that runs only for the first story.
- Call it in a decorator or in `render`, before the component mounts. The user loads once per story.

## Kea and the router

`withKea` gives each story a fresh start:

1. It resets the mocks to the defaults.
2. It unmounts every logic the previous story mounted, so an unfinished listener can't write into the next story's store.
3. It clears the cached "has data" answers that empty states read, so one story's data can't hide the next story's empty state.
4. It starts kea with an in-memory router history.
5. It mounts `featureFlagLogic`, `teamLogic`, `projectLogic`, `userLogic` and the router.

The story renders only after this reset. A story can then mount its own logics, for example with `useMountedLogic(myLogic(props))`, and drive them with actions to reach a state.
Drive a logic from a `useEffect` or a `play` function, after mount, and wait for the result with `testOptions.waitForSelector`.

## Helpers for common surfaces

- `createInsightStory(insight, mode)` in `frontend/src/scenes/insights/__mocks__/createInsightScene.tsx` mocks the endpoints an insight scene needs and renders it.
- Story-only fixtures and fakes live next to the story in a `__mocks__/` folder, for example `frontend/src/toolbar/__mocks__/`.
