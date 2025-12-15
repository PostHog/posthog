---
description: PostHog coding conventions for frontend and backend development
---

# PostHog Coding Conventions

When writing code, follow these PostHog coding conventions.

> **Source of truth**: These conventions are maintained at:
>
> - https://posthog.com/handbook/engineering/conventions/frontend-coding
> - https://posthog.com/handbook/engineering/conventions/backend-coding
>
> If this file gets out of sync, update it from the source.

---

## Frontend Coding Conventions

### Two layers: Kea -> React

Our frontend webapp is written with [Kea](https://keajs.org/) and [React](https://reactjs.org/) as two separate layers. Kea is used to organise the app's data for rendering (we call this the _data_ or _state_ layer), and React is used to render the computed state (this is the _view_ or _template_ layer).

We try to be very explicit about this separation, and avoid local React state wherever possible, with exceptions for the `lib/` folder. Having all our data in one layer makes for code that's easier to [test](https://keajs.org/docs/intro/testing), and observe. Basically, getting your [data layer](https://keajs.org/blog/data-first-frontend-revolution) right is hard enough. We aim to not make it harder by constraining your data to a DOM-style hierarchy.

Hence the explicit separation between the data and view layers.

### General tips

- Think data first: get [your mental model of the data flowing through the app](https://acco.io/i-escaped-node) right, and then everything else will be simpler.
- Be practical, yet remember that you are balancing speed of delivery with ease of maintainability. If you have to choose: code should be easier to understand than it was to write.

### Do-s & Don't-s

- General
  - Write all new code with TypeScript and proper typing.
  - Write your frontend data handling code first, and write it in a Kea `logic`.
  - Don't use `useState` or `useEffect` to store local state. It's false convenience. Take the extra 3 minutes and change it to a `logic` early on in the development.
  - Logics still have a tiny initialization cost. Hence this rule doesn't apply to library components in the `lib/` folder, which might be rendered hundreds of times on a page with different sets of data. Still feel free to write a logic for a complicated `lib/` component when needed.
  - Use named exports (`export const DashboardMenu = () => <div />`), and avoid `default` exports.
- Naming things:
  - Always look around the codebase for naming conventions, and follow the best practices of the environment (e.g. use `camelCase` variables in JS, `snake_case` in Python).
  - Use clear, yet functional names (`searchResults` vs `data`).
  - Logics are camelCase (`dashboardLogic`)
  - React components are PascalCase (`DashboardMenu`).
  - Props for both logics and components are PascalCase and end with `Props` (`DashboardLogicProps` & `DashboardMenuProps`)
  - Name the `.ts` file according to its main export: `DashboardMenu.ts` or `DashboardMenu.tsx` or `dashboardLogic.ts` or `Dashboard.scss`. Pay attention to the case.
  - Avoid `index.ts`, `styles.css`, and other generic names, even if this is the only file in a directory.
- Scenes & tabs
  - Our app is built of _tabs that contain scenes_, managed through a scene router in `sceneLogic`.
  - A scene is the smallest unit in the router and for code splitting. Usually we split scenes by resource type (dashboard, insight) and function (edit, index).
  - Each scene (e.g. Dashboards) exports an object of type `SceneExport`, containing the scene's root `logic` and its React `component`.
  - The scene's logic is automatically mounted if on a tab, and receives a `tabId: string` prop. It's strongly recommended to key your logic with this `tabId`.
  - It's also strongly recommended to add the `tabAwareScene()` function to your scene's logic. This catches bugs when mounting the logic from somewhere without the `tabId` prop.
  - Instead of `urlToAction` and `actionToUrl`, use `tabAwareUrlToAction` and `tabAwareActionToUrl`. Try to only only use them on the scene's logic, not in any deeper logics.
  - When a scene becomes inactive (you open a different tab), it's still around in the background. However any logics mounted by React components through the view layer will unmount. Use `useAttachedLogic(dataNoteLogic(propsFromComponent), mySceneLogic({ tabId }))` to attach any logic to a scene logic. It'll persist until the scene's logic is unmounted, surviving React component remounts.
  - You can control what's shown on the tab via the `breadcrumbs` selector in your scene's logic. The last breadcrumb controls the title and the icon, the one before that controls the back button. If there are more breadcrumbs, they will be ignored.
- Kea
  - It's worth repeating: think of the data flow. Then work to simplify it. Derive as much state as possible via selectors, update the source via cascading actions, and avoid complex loops where a value triggers a subscription which calls an action which changes the value which triggers the subscription, ...
  - Use `subscriptions` and `propsChanged` sparingly, only if you can't find any other way. These have a high chance of leading to messy, cyclic or slow data flows.
  - Try to write your code such that you only use `urlToAction` in your scene's logic (e.g. `insightSceneLogic`), and never deeper down in e.g. `propertyFilterLogic`.
  - Take the time and read through [the Kea docs](https://keajs.org/) until you can explain how all the various operations (actions, reducers, selectors, listeners, subscriptions, props, events, hooks, etc) work behind the scenes. It's worth knowing your tools.
- CSS
  - We use Tailwind CSS wherever possible
  - Where it's not possible
    - We use regular SCSS files for styling to keep things simple and maintainable in the long run, as opposed to supporting the CSS-in-JS flavour of the month.
    - Inside `MyBlogComponent.tsx` import `MyBlogComponent.scss`
    - Namespace all your CSS rules under globally unique classes that match the component's name and case, for example `.DashboardMenu { put everything here }`
    - We loosely follow BEM conventions. If an element can't be namespaced inside a container class (e.g. modals that break out of the containing DOM element), use BEM style names like `.DashboardMenu__modal` to keep things namespaced.
  - Keep an eye out for custom styles in SCSS files that can be easily replaced with Tailwind classes and replace them with Tailwind when you see them
- Testing
  - Write [logic tests](https://keajs.org/docs/intro/testing) for all logic files.
  - If your component is in the `lib/` folder, and has some interactivity, write a [react testing library](https://testing-library.com/docs/react-testing-library/intro/) test for it.
  - Add all new presentational elements and scenes to [our storybook](https://storybook.posthog.net/). Run `pnpm storybook` locally.

---

## Backend Coding Conventions

### Logging

As a general rule, we should have logs for every expected and unexpected actions of the application, using the appropriate _log level_.

We should also be logging these exceptions to PostHog. Python exceptions should almost always be captured automatically without extra instrumentation, but custom ones (such as failed requests to external services, query errors, or Celery task failures) can be tracked using `capture_exception()`.

#### Levels

A _log level_ or _log severity_ is a piece of information telling how important a given log message is:

- `DEBUG`: should be used for information that may be needed for diagnosing issues and troubleshooting or when running application in the test environment for the purpose of making sure everything is running correctly
- `INFO`: should be used as standard log level, indicating that something happened
- `WARN`: should be used when something unexpected happened but the code can continue the work
- `ERROR`: should be used when the application hits an issue preventing one or more functionalities from properly functioning

#### Format

`django-structlog` is the default logging library we use (see [docs](https://django-structlog.readthedocs.io/en/latest/)). It's a _structured logging_ framework that adds cohesive metadata on each logs that makes it easier to track events or incidents.

Structured logging means that you don't write hard-to-parse and hard-to-keep-consistent prose in your logs but that you log events that happen in a context instead.

```python
import structlog
logger = structlog.get_logger(__name__)
logger.debug("event_sent_to_kafka", event_uuid=str(event_uuid), kafka_topic=topic)
```

will produce:

```console
2021-10-28T13:46:40.099007Z [debug] event_sent_to_kafka [posthog.api.capture] event_uuid=017cc727-1662-0000-630c-d35f6a29bae3 kafka_topic=default
```

As you can see above, the log contains all the information needed to understand the app behaviour.

#### Security

Don't log sensitive information. Make sure you never log:

- authorization tokens
- passwords
- financial data
- health data
- PII (Personal Identifiable Information)

### Testing

- All new packages and most new significant functionality should come with unit tests
- Significant features should come with integration and/or end-to-end tests
- Analytics-related queries should be covered by snapshot tests for ease of reviewing
- For pytest use the `assert x == y` instead of the `self.assertEqual(x, y)` format of tests
  - it's recommended in the pytest docs
  - and you get better output when the test fails
- prefer assertions like `assert ['x', 'y'] == response.json()["results"]` over `assert len(response.json()["results"]) == 2`
  - that's because you want test output to give you the information you need to fix a failure
  - and because you want your assertions to be as concrete as possible it shouldn't be possible to break the code and the test pass

#### Fast developer ("unit") tests

A good test should:

- focus on a single use-case at a time
- have a minimal set of assertions per test
- explain itself well
- help you understand the system
- make good use of parameterized testing to show behavior with a range of inputs
- help us have confidence that the impossible is unrepresentable
- help us have confidence that the system will work as expected

#### Integration tests

- Integration tests should ensure that the feature works in the running system
- They give greater confidence (because you avoid the mistake of just testing a mock) but they're slower
- They are generally less brittle in response to changes because they test at a higher level than developer tests (e.g. they test a Django API not a class used inside it)

### To ee or not to ee?

We default to open but when adding a new feature we should consider if it should be MIT licensed or Enterprise edition licensed. Everything in the `ee` folder is covered by [a different license](https://github.com/PostHog/posthog/blob/master/ee/LICENSE). It's easy to move things from `ee` to open, but not the other way.

All the open source code is copied to [the posthog-foss repo](https://github.com/posthog/posthog-foss) with the `ee` code stripped out. You need to consider whether your code will work if imports to `ee` are unavailable.
