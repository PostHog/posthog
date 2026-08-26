# Canvas (Website space) — patterns

Conventions for the channel-scoped Website space: channels and canvases. A canvas
is an agent-authored browser app rendered in a sandboxed iframe. Read this before
changing breadcrumbs, canvas naming, or the canvas generation harness. The root
`AGENTS.md` architecture rules still apply.

## Components & styling

- **Use `@posthog/quill`, never Radix.** All UI in this space pulls components from
  `@posthog/quill` (`Button`, `Dialog*`, `AlertDialog*`, `DropdownMenu*`,
  `ContextMenu*`, `Tooltip*`, `Collapsible*`, …). Adding a `@radix-ui/themes` or
  `@radix-ui/react-*` import is banned — see [UI Components](../../../../../AGENTS.md#ui-components)
  in the root `AGENTS.md` for the full mapping. Some older code here still imports
  `@radix-ui/themes` (`Box`, `Flex`, `Text`, `AlertDialog`) — that's legacy to be
  migrated, not a pattern to copy. When you touch such code, replace it: layout
  primitives (`Box`, `Flex`, `Grid`) become `div`s with Tailwind classes
  (`<Flex align="center" gap="2">` → `<div className="flex items-center gap-2">`),
  and everything else becomes its Quill equivalent.
- **Don't restyle Quill internals.** Quill components are already themed —
  spacing, typography, and especially **color** are baked in. Do not add
  `text-gray-*` / `text-muted-foreground` / `font-*` or other color/typography
  classes to elements *inside* a Quill component (menu items, dialog titles,
  buttons, etc.); you'll fight or override the design system and drift from every
  other surface. Trust the defaults. Layout-only utilities (`flex`, `gap`,
  width/`max-w`, `truncate`) on wrappers are fine; reach for `className` overrides
  on Quill items only when there is a real, deliberate exception — and call it out.
- **Suffix `…` on anything that opens another step.** A menu item or button whose
  click opens a follow-up surface — a dialog, a nested menu, a picker, a
  confirmation — gets a trailing ellipsis (`…`, the character, not three dots) to
  signal it isn't the final action: `New…`, `Rename space…`, `Delete space…`,
  `Choose a template…`. A label that performs its action immediately or navigates
  straight to a destination gets **no** ellipsis (`Edit CONTEXT.md`, `Star
  space`). When in doubt: does clicking it ask for more input or confirmation
  before anything happens? If yes, add the `…`.

## Spaces & chrome

- Spaces is a rail destination, gated behind `project-bluebird` and wired in
  `routes/__root.tsx`.
  The rail's destinations and the paths they claim live in one table,
  `railPane.ts`: Home (`/`), Spaces (`/spaces`), Activity (`/activity`),
  Inbox (`/inbox`), Command Center (`/command-center`), Loops (`/loops`).
  Unclaimed routes belong to Spaces.
  Only Spaces and Activity own the column beside the rail; the rest are
  whole-screen, so no route under them may draw a second nav.
- **A rail pick returns you to where that destination was**, not to its index.
  `BrowserTabStrip` records the settled route per destination in the active
  tab's `viewState.lastByPane`, and `pickRailDestination` replays it. Only Spaces
  carries sidebar state on top of its href. Clicking the destination you are
  already on never restores — it runs `onReclick`, which for Spaces means the
  list.
  Anything a destination does besides navigating must live in its route
  component, not its `onPick`: the restore path navigates by href and never
  reaches the navigation bridge.
- **Testing flag-off locally:** dev builds default `project-bluebird` and
  `code-spaces-layout` on, and that default beats posthog's own override. Force
  them off with
  `localStorage.setItem("ph-dev-flags-off", "project-bluebird,code-spaces-layout")`
  and reload (see `devFlagOverrides.ts`). Bluebird-only paths are listed in
  `bluebirdRoutes.ts`; a flag-off user who restores one lands on a new task.
- Routes are flat, and the ones wearing the spaces chrome are grouped under the
  **pathless** `_shell` layout rather than a URL prefix.
  Match `fullPath` (the route's own pattern) rather than the resolved URL when
  deciding what a route is: a space id could otherwise impersonate a
  destination.
- The Spaces UI has **its own chrome**: rail + a persistent channel-list
  sidebar (`ChannelsList`, rendered in `__root`) + the `ShellLayout` outlet. It
  does NOT use the code `HeaderRow`/`MainSidebar`, so breadcrumbs render in
  `ShellLayout`'s own top bar (below).
- Under the channels layout the sidebar is a **master/detail slider**
  (`ChannelPanes` in `ChannelsSidebar.tsx`): the searchable channel list, and the
  channel you're in (`ChannelSidebar`, headed by `ChannelBackRow`). Both panes
  stay mounted — the offscreen one is `inert` — so the slide has something to
  slide and returning to the list doesn't rebuild every row. A two-finger
  horizontal swipe moves between them (`useChannelPaneSwipe`, wheel `deltaX`
  accumulated per gesture and locked until the wheel goes quiet). The track
  animates only for a space-row click or the back row; tab restoration, route
  sync, hotkeys, rail restoration, and swipes snap directly to their pane so
  unrelated navigation never moves the sidebar across the reader.
- In the list, "Starred"/"Spaces" are headings above lightly indented rows. The
  private "personal" row leads the Starred section and takes the same inset as the
  spaces beside it. It is the one row that carries a glyph: the lock is the only
  thing saying nobody else can see this space, which is worth its name starting a
  glyph's width right of the others. The alpha's more deeply indented Channels
  tree and hash glyphs are unchanged.
- **The private space reads as "personal" without a hash, and only on screen.** The row is `me`
  on the backend; `channelDisplayName` (core) swaps it on the way to a reader.
  `channelDisplayLabel` adds a hash to shared spaces but leaves personal bare.
  Four routes carry a channel's name — the channel list, an activity row, a
  mention row, and remote search — and each calls it, because only the first
  goes through `useTaskChannels`.
  Recognition of a full channel object goes through `isPersonalChannel`/`isGeneralChannel`
  (`@posthog/core/canvas/channelName`), which check `system_role` first and fall back to
  `channel_type`/name for a server that predates the field — never the name alone.
- **The lock follows what a space is, not what it is called.** `channelGlyph`
  takes a `personal` flag; a caller holding the channel object should pass
  `isPersonalChannel(channel)` rather than `channelType === "personal"` directly, and the
  name match behind it is a fallback for surfaces that hold only a bare name.
  A public space named `personal` used to wear the lock while the real private
  space showed none, which is a space impersonating yours.
  `validateChannelName` reserves `personal` and `me` so the create and rename
  forms refuse them — client-side only, so it neither binds the API nor renames
  a space that already took one.
- **The list is a tree.** Each space has a disclosure caret that opens it onto
  its most recent sessions (`useRecentSpaceTasks` — one task query per open
  space, polling slower than the channel feed; expansion lives in
  `spaceTreeStore` and persists). Session rows wear the space's own session
  vocabulary (`TaskStatusDot` + `TaskBadgeStack`) but are hand-built rather than
  `ChannelItemRow`: a row has to be an `AutocompleteItem` to stay on the
  keyboard's path, and that row is a `SidebarItem` button.
- **An open space offers the sessions it isn't showing.** A "View all" leaf
  closes the list with what's left over and opens the space.
  Its number comes from `getTasksPage`, which returns the page's total alongside
  its rows: a page that came back under the fetch limit is the whole space
  (exact once archived ones are dropped), a full one falls back to the server's
  count, which still counts archived tasks.
  `hasViewAllRow` decides whether that leaf exists, and both the rendered list
  and the keyboard's flat node list have to call it: a row the keyboard doesn't
  know about throws the highlight index off from there down.
- **A session row carries the same card and menu as the space's own list.**
  Both surfaces render `ChannelItemHoverCard` and `TaskRowContextMenu` from one
  `TaskRowMenuProps`, so the facts and the actions can't drift.
  Rename is the one item the tree drops, because it edits in place and there is
  no inline editor on a row the keyboard is walking.
  The card also opens on the keyboard's highlight, 350ms after it lands — on a space row as well as a session one, so walking the tree shows the same card whichever kind of row the highlight lands on.
  The row that opened it is the only one that may take it away (`openFromKeyboard` / `closeFromKeyboard` on the provider, released the moment a pointer enters any row): the pointer moves the same popup between rows without telling the row that opened it, so an unconditional close on the next keypress reached across and shut a card the pointer was on.
  Rows read that highlight from `spaceTreeStore` as a boolean
  (`highlightedValue === item.key`) so a keypress re-renders two rows, and the
  list still writes it to a ref as well, because the arrow handlers read the
  highlight during the event, before any render.
  Only a `reason: "keyboard"` highlight is stored: a pointer one is the row's
  own hover, and `keepHighlight` would otherwise strand a card open after the
  pointer left the list.
  The actions behind the menu (`useSpaceTaskActions`) are built once for the
  whole list and passed through `SpaceTaskActionsProvider`, which keeps one pin
  and one archive mutation for the tree instead of one per row and keeps them
  out of the memo comparisons.
- **There is one card, not one per row.** `ChannelItemPreviewCardProvider`,
  mounted once around the whole sidebar, owns the popup; a row is only a
  `PreviewCard.Trigger` on its handle, carrying what the card should say as the
  trigger's payload.
  So the card's queries and derivations run for the row being pointed at rather
  than once per row in the list, and Base UI skips the open delay when the
  pointer crosses to another trigger of a card that is already open — which is
  the point: sliding down the list moves one card instead of re-waiting 400ms
  on every row.
  Two things keep that working: a row's payload has to stay referentially stable
  (memoize the `menu`), and a surface that lists rows has to sit under the
  provider, or its rows get no card at all.
- **A space has a card too, on the same handle.** `SpaceHoverCard` is a trigger on the one popup the session rows use, so crossing from a space to a session under it swaps the card's contents instead of closing one popup and opening another. The payload is a discriminated union (`ChannelPreviewPayload`), and `kind` picks `SpacePreview` or `ChannelItemPreview`.
  It shows who has been working in the space, what it is wired to, and the counts the row draws as dots: the creator leads the avatar group wearing a crown, then whoever ran the newest sessions.
  The people are not a membership list — the backend has none. They come from `useSpaceOverview`, off the same `space-tree-tasks` page the tree's rows are built from, which the row's own hover prefetch has already warmed, so the card costs no request.
  The group is `reverse`d, so each face tucks behind the one after it — which puts the creator's right corner under its neighbour, so the crown goes on its left corner instead.
  `useChannelActions` memoizes its action list, and `ChannelSection` memoizes the payload, because both travel to the card's store on every identity change. Its memo comparator also compares `repositories` by content — the channel list is polled and hands out a new array each time.
- **The card names the row's marks rather than inventing a second scale.**
  It spells out the dot's own label and the badges' (`taskDot`, `taskBadges`),
  and shows the last thing the agent said.
  It used to show the run's raw status ("Ready", "In progress"), a vocabulary
  the rows dropped when the dot took over, which left a quiet row sitting under
  a green "Ready".
  The message comes from `useLatestTurnMessage`: the live session's events where
  this window has the session, otherwise the closing prose a cloud run persists
  to `latest_run.output.final_message`.
  Neither costs a request.
- **The open session's header wears the same marks under bluebird.** `TaskHeaderMark` / `TaskHeaderActions` (task-detail) draw `taskDot` and `taskBadges` around the title, from `useTaskStatusInput` — the row hook's task-shaped half, which `useChannelTaskStatus` now delegates to.
  Off the flag the header keeps its workspace-mode glyph, and the PR lookup is skipped with it.
  So the cloud glyph goes: it said where the run lives and nothing about whether the run wants anything, and in this vocabulary cloud is silent — running there is the default, so only the local exception earns a badge.
- **After the title they are controls, not an avatar stack.** The header is one line about one session, sitting beside a live copy-link button, so what it can act on it draws as quill icon buttons: the pin toggles (always shown, filled when pinned), and a badge carrying a `url` opens it.
  Badges with nothing to go to — `Local`, a plain origin — stay marks with a tooltip, sized to the button box so the row doesn't step as badges come and go.
  The PR badge is dropped here: `TaskActionsMenu` sits at the end of the same row and already draws the PR in its lifecycle colour with its actions behind it.
- **The card's badges are buttons where they point somewhere; the row's never are.** A row is a `<button>`, so its badges stay spans — the card isn't, so a badge carrying a `url` opens it externally and is underlined, dotted, to say so.
  `taskBadges` sets the url on the PR badges, and on the origin badge for Slack — the one origin that hands back a place to go (`slack_thread_url` off the run's state), rather than just naming itself.
  A PR's url reaches the badge by two routes: a cloud run's `pr_url`, or the one the host cached against the task, which `getTaskPrStatus` returns alongside the state so a local PR is clickable too.
- **The card's `Item`s are `flex-nowrap`, and neither card has a gutter.** quill's `Item` wraps, and a message with a url in it has a min-content wider than the card, which dropped the whole text column onto a line of its own and out past the card's edge.
  `min-w-0` on the `ItemContent` and `break-words` on the message keep it inside. The `Crowded` story is that case.
  A row's mark rides beside the title rather than in an `ItemMedia` column: one glyph on one line does not earn an indent down the whole height of the card.
- **A row's own colour utilities outrank quill's highlight styling.** quill
  brings a highlighted option's contents to `--foreground` with
  `.quill-autocomplete__item[data-highlighted] *`, but that rule lives in the
  components layer, so anything carrying a colour utility of its own wins and
  keeps its resting colour under the keyboard.
  Row labels therefore state the highlight themselves (`ROW_LABEL_TONE`), and
  the disclosure caret, which must stay dim while its row is highlighted, needs
  `!` on a rule aimed at the glyph's descendants, because the `*` reaches the
  icon's `<path>` where `fill: currentColor` resolves.
- **The tree's rows are memoized, and have to stay that way.** A space row
  carries a context menu, two dropdowns, a tooltip and two dialogs, and there
  are dozens of them; before `ChannelSection`/`PersonalChannelRow`/`SpaceTaskRow`
  were `memo`ed, expanding one space rebuilt every other row (350-540ms per
  expand, in 300ms chunks). Keeping that means keeping their props stable: the
  toggle callback takes a space id instead of closing over one, empty session
  lists are a shared constant, `useRecentSpaceTasks` caches each space's item
  list against the query data it was built from, and its `combine` is defined at
  module scope so `useQueries` can memoize on it. A row's `channel` is compared
  field by field, because the channel list is polled and hands out new objects.
- **The tree stays off the host.** Its rows skip the per-task PR lookup
  (`useChannelTaskStatus(item, { withPrStatus: false })`) — that is a query per
  row into git, and the tree can show a dozen spaces' worth at once; the PR's
  existence still shows, because `prUrl` comes from the task itself. Its feed
  query is its own key with a 20-row page, not the channel feed's 500: sharing
  the feed's key would hand the space's own list a truncated feed.
- **Hover prefetch waits for the pointer to rest** (250ms). Arrowing through the
  tree scrolls rows under a stationary cursor, so prefetching straight from
  `pointerenter` fired a request for every row the list passed and made each
  keypress take a second.
- **Keyboard contract of the list.** `SidebarSearchHeader` gives Spaces and
  Activity the same title and search treatment. Its shared focus request means
  ⌘⇧S opens the sidebar and focuses whichever search is visible. Both lists
  are permanently open inline Autocompletes: the search box keeps focus while
  ↑/↓ walk every visible row and Enter opens it. In Spaces, the input also
  drives the tree: → opens the highlighted space (and
  again steps into it), ← closes the space you're in and puts the highlight back
  on it. Both arrows defer to the text caret first, so they still edit the
  query. From elsewhere, ⌘⇧S slides Spaces back to the list and takes the
  keyboard; it is advertised on the search box (until a query replaces it
  with the clear button) and on the space's back row, which is what it does from
  inside a space. Autocomplete has no API for setting the highlight, so moving it
  means synthesizing the arrow keys it listens for — and moving *before*
  collapsing, while the rows still exist.
- One `ChannelsFab` serves both panes: given a `channelId` it creates a task in
  that channel; from the list, where nothing else offers it, it creates a space
  instead. Off the layout it keeps its original two-item menu.
  Archived moves out of the sidebar and into the account menu
  (`ProjectSwitcher`), beside Settings.
- **Activity mixes task updates with a bounded Self-driving preview.** Both
  `ActivityFeedList` and `ActivityView` merge their task activity with up to
  three reports matching Activity's persisted Inbox filters, then sort and group
  the combined rows by activity time. The Activity actions menu has an Include
  section: Mentions are on by default and Self-driving is off. Enabling
  Self-driving reveals its P1/For you defaults plus scope, source, PR state,
  sort, and priority filters without changing the Inbox page's filters. Inbox
  reports do not have the task activity read model, so the unreads-only view
  hides them. If more than three match, the overflow row copies Activity's Inbox
  filters into `/inbox/reports` before opening it.
  Picking a preview report stays on `/activity` and renders that already-loaded
  report beside the feed while its detail query refreshes in the background.
- **Which pane shows is view state, not a route.** `channelPaneStore` holds it,
  separately from the scoped channel (`currentChannelStore`): "back to channels"
  browses the list while the route, the main pane and the scoped channel stay
  put. Every way into a channel — a row click, a deep link, a mention, ⌘1-9 —
  ends at `showChannelPane()`, directly or through the route effect.
  The one exception is a session opened from the list's tree: it loads in the
  main window and leaves the sidebar on the list, because picking a session
  while browsing across spaces is not a request to go into one. It says so with
  `keepListForRoute(spaceId)`, which the route effect checks in place of sliding;
  the first-run landing on #general uses the same latch.

## Breadcrumbs

- **`ShellLayout` renders its own top bar.** The Spaces UI has no code
  `HeaderRow`, so breadcrumbs (and the dashboard controls) are a local bar inside
  `ShellLayout`, not pushed through the header store.
- **A page does not get its own crumb — its H1 is the title.** A view that
  renders its own `<h1>` is NOT repeated as a breadcrumb segment for itself. The
  dashboards grid's h1 is "Dashboards"; a single dashboard's h1 is its name.
- **A parent index IS a crumb when you're on a child, but not when you're on it.**
  - On the grid (`/spaces/$channelId`): trail is `#channel` only — no
    "Dashboards" crumb (its own h1 covers it, and `#channel` already links here).
  - On a single dashboard (`/spaces/$channelId/dashboards/$id`): trail is
    `#channel / Dashboards`, where `Dashboards` links back to the grid. The
    dashboard's name is the h1 below, not a crumb.
- Crumbs reflect navigable parents above the current page; the current page is
  the H1, never a crumb of itself.

## Canvas naming

- **A canvas's name is its own field on the record**, set at creation
  (`Untitled canvas` by default; `useCreateAndOpenDashboard` drives it). It is
  independent of any heading the agent renders inside the React app.

## Storage

- Canvases are **first-class PostHog rows** (the `canvases` API), not local
  files. Each canvas belongs to a backend channel (`channelId`), and its
  agent-authored source lives in **server-side versions**: every publish
  appends an immutable source version, guarded by `expected_current_version_id`
  so concurrent publishes conflict (409) instead of clobbering. The rendered
  output is the published build's artifact, served from the isolated artifact
  origin. See `@posthog/core/canvas/dashboardsService.ts` and
  `dashboardSchemas.ts` for the record/source/version shapes.
- **Two components render a canvas, and `FreeformCanvasView` picks between
  them.** A build's artifact renders in `BuiltCanvas`; a canvas with no
  successful build yet falls back to the head project's single
  `CANVAS_COMPONENT_PATH` file in the `FreeformCanvas` srcDoc sandbox (which
  transpiles in-browser and resolves imports off esm.sh). Both go through the
  same `canvasHostMessageRouter`, so protocol and guard changes belong there
  rather than in either host.
- **Capabilities gate viewers, not authors.** `assertCanvasCapability` runs only
  in `BuiltCanvas`, against the manifest frozen into that build. The edit path is
  deliberately full-access — the author is running their own code against their
  own session — so the asymmetry is the design, not a gap to close. See the
  two-tier security model in `docs/CANVAS-FREEFORM-REACT-PLAN.md` before changing
  what either tier may reach.

## Channel sidebar preloading

- A channel's contents load **lazily on expand**: `ChannelSection`
  (`components/ChannelsList.tsx`) only passes a real `channelId` to its content
  queries once `open` is true, so the tree doesn't fire one query per channel on
  mount.
- To keep first-open instant, the same caches are **warmed on hover/focus**:
  `ChannelSection.prefetchContents()` runs from the row's `onMouseEnter` /
  `onFocus` and prefetches every per-channel query. Each prefetch hook reuses the
  query's `queryOptions` with the **same `staleTime`** as the live query, so it
  no-ops when the data is already fresh.
- **Rule: lazy-loaded content and preloading must stay in lockstep.** When you
  add a new per-channel item type to the expanded tree (a new query gated on
  `open`, like dashboards or filed tasks), you MUST also:
  1. add a `usePrefetch…` hook next to that query (mirror `usePrefetchDashboards`
     in `hooks/useDashboards.ts` / `usePrefetchChannelTasks` in
     `hooks/useChannelTasks.ts` — same key, same `staleTime`), and
  2. call it inside `ChannelSection.prefetchContents()`.

  Otherwise the new content cold-fetches on first expand and reintroduces the
  open jank the prefetch path exists to prevent.
