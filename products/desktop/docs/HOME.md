# Home

Home is the app's first destination: the page PostHog Desktop opens on, built
out of work that already exists in PostHog rather than out of an empty prompt.
It sits left of Inbox in the spaces nav (`ChannelNav`) and lives at
`/website/home`, behind `posthog-desktop-home` (which itself requires
`project-bluebird` — see `useHomeEnabled`).

## The shape

Home is a single scroll column of stacked blocks, all wearing the same frame
(`HomeSection`), so a page assembled from separate surfaces reads as one page:

1. **Hero.** The org's mark × PostHog's, "Welcome to PostHog Desktop", and one
   line counting what is below.
2. **Suggestions.** Recent feature flags, each offering the one move Home can
   make on it: give the flag a space (`#feature-<key>`), so the work behind it
   has somewhere to happen. A flag whose space already exists opens it instead.
3. **Experiments.** What is running, how long it has been running, and a way
   into the results.
4. **Your canvases.** The canvases pinned in your personal space, each rendered
   as a real, live canvas in its own sandboxed frame, laid one under the next.

Blocks 1–3 are the app's own components. Block 4 is where the stacking idea is
literal: several independent canvases, each with its own build, its own data
requests, and its own author, presented as consecutive sections of one page.

## Why pinning

A canvas already carries `pinnedAt`, and the canvas toolbar already sets it. So
"what shows on my Home" needed no new concept: pin a canvas in your personal
space and it joins the stack, in pin order; unpin it and it leaves. The cap is
`HOME_CANVAS_LIMIT` (3) because each stacked canvas is a live iframe, and past a
handful the page costs more to open than it saves.

## Prefetching

Home exists to save the trip to find the work, which a page that fetches as you
scroll would undo. So every group loads on mount, and the rail's Home button
warms the work cache on pointer-enter (`usePrefetchHomeWork`) — by the time the
click lands, the page usually has its data.

`HomeService` (core) reads both groups in parallel through the shared
`ProjectApiClient`. A group that fails to load comes back in `unavailable`
rather than failing the whole call, and Home says so: an empty Experiments
section and a missing `experiment:read` scope look identical otherwise.

## Layering

| Piece | Where | Job |
| --- | --- | --- |
| `HomeService`, `homeSchemas` | `packages/core/src/home/` | Read + normalize feature flags and experiments; rank them; report unreadable groups |
| `home.router` | `packages/host-router/src/routers/` | One-line forward |
| `useHomeWork`, `useHomeCanvases`, `useHomeOrg` | `packages/ui/src/features/home/` | One query each |
| `homeSuggestions` | `packages/ui/src/features/home/` | Which flags to offer, and whether their space exists |
| `HomePage` | `packages/ui/src/features/home/components/` | The page body, entirely from props (so Storybook can show it) |
| `HomeView` | `packages/ui/src/features/home/` | The container: hooks in, `HomePage` out |

`HomePage.stories.tsx` renders the page with fixture data, including an empty
Home and a Home missing a group.

## What else a personal Home could show

The sections shipped so far are the two groups the desktop can read cheaply
today. The list below is the backlog of candidate blocks — each one is a
section, and each could be either an app component or a canvas. They are sorted
roughly by how directly they answer "what should I do next?".

### Work you already started

- **Sessions still running.** Agent runs in flight right now, local and cloud,
  with the last thing each agent said. The one block that is genuinely
  time-sensitive; everything else can be a day stale.
- **Waiting on you.** Runs stopped on a permission prompt or a plan approval.
  A stalled run is invisible today unless you go looking for it.
- **Your open PRs, by state.** Ready to merge, failing CI, waiting on review,
  review comments unanswered. The inbox counts these; Home could show the three
  that need a decision.
- **Branches without a PR.** Worktrees with commits that never became anything.
  Either finish it or throw it away — Home is a good place to be asked.
- **Yesterday.** What you shipped, merged, or closed since you last opened the
  app. Ends the "where was I?" reconstruction.

### Work the product is asking for

- **Flags stuck at a percentage.** A flag that has sat at 25% for three weeks is
  a decision nobody made. Offer: finish the rollout, or remove the flag.
- **Flags that are fully rolled out.** 100% for a fortnight with no experiment
  attached is dead code plus a config row. Offer: a cleanup task.
- **Experiments that reached significance.** The result is in and nobody
  shipped it. Offer: ship the winner, or write the conclusion.
- **Experiments with no exposures.** Launched, but nothing is arriving —
  usually a broken integration, and always worth knowing on day one rather than
  at the end of the run.
- **Error tracking issues in code you touched.** New or spiking issues whose
  stack frames land in files from your recent PRs. This is the block most
  likely to change what someone does with their morning.
- **Inbox reports that became tasks.** What the scouts filed, and what happened
  to it.

### The shape of your own work

- **Your spaces, by heat.** Which spaces have moved this week and which have
  gone quiet. A quiet space is either finished (archive it) or stuck (say so).
- **Repos you actually work in.** Ranked by your recent sessions, with each
  repo's current branch state, so opening one is a click instead of a picker.
- **Cost and usage.** What your agent runs cost this week, against the plan.
  Belongs on Home only when it is close enough to a limit to change behavior.
- **Your review queue.** PRs from teammates that name you, with how long they
  have been waiting.

### Things only a canvas can do

Each of these is more useful as an agent-authored canvas than as a shipped
component, because the question is personal and the answer changes shape:

- **A metric you personally watch.** One number, your framing, your date range.
- **A weekly digest of your own product area,** written by an agent against
  your project's data and pinned once.
- **A checklist for a migration you are running,** where the checkboxes are
  queries rather than state a person keeps up to date.
- **A scratch board for an investigation,** kept for as long as the
  investigation lasts, then unpinned.

The point of the stack is that the last four are indistinguishable from the
first three, to a reader. Home is a frame; what goes in it can be shipped code,
or a canvas somebody wrote on Tuesday.

## Next steps, in order

1. **Sessions in flight and waiting-on-you.** The only genuinely time-sensitive
   blocks, and both read from data the app already holds.
2. **Make Home's own blocks canvases.** The hero and suggestions are components
   today. Once a section can be a canvas template instantiated per user, they
   become editable: "make the suggestions section only show billing flags".
3. **Ordering.** Pin order controls the canvas stack; nothing controls whether
   Experiments sits above or below it. Drag-to-order, persisted per device, is
   the smallest version.
4. **`/website` lands on Home.** The spaces index currently redirects to the
   first channel. Home is a better landing page, but changing it moves the
   whole spaces world, so it wants its own decision.
5. **A canvas height that follows its content.** The stack gives each canvas a
   fixed band because the canvas runtime reports no content height. A
   `content-height` message on the bridge would let a short canvas be short.
