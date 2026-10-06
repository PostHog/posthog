# Deterministic stories

A story renders a light and a dark visual review snapshot on every run that selects it.
A story that renders two different pictures for the same code blocks unrelated PRs, collects tolerations, and ends up quarantined.
Every pattern below caused a real quarantine. Each one has a fix that removes the race instead of hiding it.

## What the runner already does

`common/storybook/.storybook/test-runner.ts` turns off animations and transitions, makes lazy images eager and waits for them to decode, preloads fonts, waits for the known loader selectors to disappear, waits for network idle, and sets the theme on `body[theme]` before each snapshot.
Do not add your own waits for these.
The runner does not know when your own async content is done, when a timer changes the UI, or when a component measured itself at the wrong size.

## Pin the clock

Relative text ("3 days ago", "2 years ago") changes as the wall clock moves, so a story that passes today fails next week on every branch at once.
Set `parameters.mockDate`, and write the dates in mock data relative to that date.

## Wait for readiness, not for existence

`testOptions.waitForSelector` waits until the selector matches. Pick an element that only exists after the async work is done.
A container that renders before its data loads does not help.

- Monaco: wait for `.CodeEditor[data-editor-ready="true"]`. `.monaco-editor` also matches Monaco's shared overflow root on `<body>`, which exists before any editor mounts.
- A panel that loads its own data after the page loader is gone: wait for an element that renders only from the loaded data, for example a button that shows only when the list arrived empty.

Mock every request the story fires with `mswDecorator`. An unmocked request can resolve after the snapshot.

## Give self-measuring content a fixed width

`layout: 'padded'` makes `#storybook-root` an inline block that shrink-wraps its content (`frontend/src/styles/base.scss`).
Content that measures its container when it mounts (Monaco, charts, React Flow) then takes whatever width the root had at that moment.
The first story in a file is the usual victim, because the layout class lands right before its snapshot.
Wrap the content in a fixed width (`w-[42rem]`), not a `max-w-*`.

## Do not let the viewport set the height

The app shell has `min-height: 100vh`. When the content is taller than the viewport, the snapshot height follows the viewport height at capture time, and a taller viewport adds a blank strip.
Let the shell hug the content in that story, for example with a decorator that sets `.Navigation3000 { min-height: 0 }`.

## Wait for timers to settle

UI that changes on a timer (player controls that hide after 1.5 seconds, toasts, auto-collapsing panels) gives a different picture depending on when the snapshot fires.
In the `play` function, wait for the settled state, not the first state.
For example, wait until the controls are visible and then until they are hidden again.

## Read the theme from the DOM

The runner switches the theme by setting `body[theme]`. A component that reads a logic value such as `isDarkModeOn` can lag one render behind and draw the first frame in the wrong theme.
Read `document.body.getAttribute('theme')`, or a hook that reads it.

## Do not chain layout on previous state

A computation that uses the current state to produce the next one (for example React Flow `fitView` padding computed from the current zoom) lands on a different result depending on how often a resize observer fires.
Compute from the target state (the zoom the fit lands on), and clamp it to the same limits the library uses.

## Canvas charts

A resize resets a canvas bitmap, and the redraw runs on the next animation frame.
If the chart region changes size while the page settles (for example because a footer wraps after the chart width changes), the snapshot can catch an empty canvas.
Keep chart containers at a fixed size in stories, and avoid content around the chart whose height depends on the chart width.

## Find the variant before you fix it

Look at both pictures before you change anything.
`posthog:visual-review-repos-flakiness-retrieve` lists the stories that flaked on the default branch, and the run snapshots carry the baseline and the variant image.
The diff region usually names the cause: a strip at the bottom is a height race, an empty chart is a canvas reset, a shifted block is a width race, a skeleton is a late load.
Some "flakes" are a stale or wrong baseline. Compare the variant with the git history of `frontend/snapshots.yml` before you change the story.
