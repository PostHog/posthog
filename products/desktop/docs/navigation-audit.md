# PostHog Desktop navigation audit

Date: 2026-08-22  
Scope: `products/desktop` renderer navigation, with emphasis on the Channels/Spaces layout and its left rail.

## Executive summary

The desktop app currently has two navigation surfaces behind one TanStack Router shell:

1. The legacy Code sidebar, which owns task creation, search, Inbox, Activity, Command Center, Loops, and settings.
2. The newer Channels/Spaces layout, which adds a fixed left rail, a resizable sidebar, a Space list/detail slider, and channel-scoped routes.

The URL is the source of truth for the rail's selected destination. Rail destinations that own a full page navigate to a different route, so the large content pane changes. Spaces is intentionally different: it is both a route family and a sidebar browser. Clicking Spaces first shows the list; if the user is already inside a Space, it can only change the sidebar pane while preserving the current Space route and main content.

The current implementation therefore has a deliberate two-state model:

```text
route state       = what owns the large content pane and which rail item is active
view state        = whether the Spaces sidebar shows the list or the scoped Space
scoped state      = which Space remains selected while the list is being browsed
```

This is mostly coherent, but it creates several user-visible asymmetries: Inbox always exits the Channels chrome, Home/Command Center/Loops are full-page destinations, and Space task selection changes the main pane while intentionally leaving the Space list visible. Those behaviors are documented in code but are not uniform across every navigation entry point.

## Overall shell

The root route mounts the shell and an `Outlet`. When the Channels layout flag is enabled, the shell is arranged as follows:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ title bar: app mark · sidebar toggle · back/forward · search · Web           │
├──────────┬──────────────────────┬───────────────────────────────────────────┤
│ NavRail  │ ChannelsSidebar      │ main content                               │
│          │                      │                                             │
│ Home     │ list OR activity     │ route Outlet                               │
│ Spaces   │ OR Space detail      │                                             │
│ Activity │                      │ /website/...                               │
│ Inbox    │                      │ /code/...                                  │
│ Command  │                      │ /command-center                            │
│ Loops    │                      │                                             │
│          │                      │                                             │
│ Settings │                      │                                             │
│ project  │                      │                                             │
└──────────┴──────────────────────┴───────────────────────────────────────────┘
```

Relevant composition is in [`__root.tsx`](../packages/ui/src/router/routes/__root.tsx:280): the rail is outside the sidebar, the sidebar is rendered only for destinations that claim a sidebar, and the route outlet owns the large pane. Settings is a separate full-page shell without the normal rail/sidebar chrome.

When the Channels layout is disabled, `NavRail` is absent and the same root shell renders the older `ChannelsSidebar` in Code mode. In that mode the sidebar contains `SidebarNavSection`, task navigation, and the project switcher.

## Rail destination map

The current rail is defined in [`railDestinations.ts`](../packages/ui/src/features/canvas/components/railDestinations.ts:82).

```text
click
  │
  ├─ Home ────────────────> navigate /website/home
  │                          └─ main pane = WebsiteHome
  │
  ├─ Spaces ──────────────> showChannelList()
  │                          │
  │                          ├─ already on Spaces route
  │                          │    └─ sidebar slides to Space list only
  │                          │       route and main pane stay unchanged
  │                          │
  │                          └─ elsewhere
  │                               ├─ scoped Space exists
  │                               │    └─ remember it, navigate /website/{id}
  │                               │       sidebar remains on list
  │                               └─ no scoped Space
  │                                    └─ navigate /website
  │
  ├─ Activity ─────────────> navigate /website/activity
  │                          ├─ Channels layout: sidebar = activity feed
  │                          └─ main pane = selected activity detail
  │
  ├─ Inbox ─────────────────> navigate /code/inbox
  │                            └─ leaves Channels chrome; main pane = Inbox
  │
  ├─ Command Center ───────> navigate /website/command-center
  │                            └─ main pane = CommandCenterView with Channels chrome
  │
  └─ Loops ─────────────────> navigate /code/loops
                               └─ leaves Channels chrome; main pane = LoopsListView
```

The selected rail item is computed from the deepest route match in [`railPane.ts`](../packages/ui/src/features/canvas/railPane.ts:19). Unclaimed routes default to `spaces`, which means channel routes, channel tasks, channel canvases, `/website`, and most non-destination routes light Spaces.

```text
deepest route match
  │
  ├─ /website/home*             => Home
  ├─ /website/activity*         => Activity
  ├─ /website/command-center*  => Command Center
  ├─ /command-center*           => Command Center
  ├─ /code/inbox*               => Inbox
  ├─ /code/loops*               => Loops
  └─ anything else              => Spaces
```

This route-derived selection avoids stale highlight state. The tests explicitly cover channel loops/context/task routes remaining under Spaces rather than being mistaken for the Code Loops destination ([`NavRail.test.tsx`](../packages/ui/src/features/canvas/components/NavRail.test.tsx:73)).

## Spaces list/detail behavior

The Spaces sidebar is a two-pane slider. `pane` is local Zustand view state; it is not represented in the URL. `currentChannelId` is a separate local scoped id. Both panes remain mounted, and the hidden pane is inert.

```text
currentChannelId = Space A       pane = "channel"
                                      │
                 showChannelList()  │  showChannelPane()
                                      ▼
currentChannelId = Space A       pane = "list"
```

This explains the important behavior:

```text
Space list visible, click Space A
  ├─ showChannelPane()
  ├─ setCurrentChannel(Space A)
  └─ in Channels layout: do not navigate
       => sidebar changes to Space A
       => main pane stays on its existing route

Space list visible, click a task under Space B
  ├─ keepListForRoute(Space B)
  ├─ setCurrentChannel(Space B)
  ├─ navigate /website/Space-B/tasks/Task
  └─ ChannelRouteSync consumes the latch
       => main pane changes to the task
       => sidebar intentionally remains on the list

Space A visible, click Spaces rail
  ├─ showChannelList()
  └─ because route is already a Spaces route, stop
       => only sidebar changes from Space A to list

Inbox/Home/Activity/etc., click Spaces rail
  ├─ showChannelList()
  ├─ read currentChannelId
  ├─ if present: keepListForRoute(currentChannelId)
  └─ navigate /website/currentChannelId
       => main pane changes into that Space
       => sidebar remains on list
```

The latch is keyed by Space id rather than consumed blindly. This protects the intended list state against React StrictMode effect re-runs and prevents it from leaking through a later channel-less navigation. [`ChannelRouteSync.tsx`](../packages/ui/src/features/canvas/components/ChannelRouteSync.tsx:25) then either opens the channel pane for ordinary route entry or preserves the list for a latched task/list transition.

## Space route families

```text
/website
├─ /                         WebsiteChannelsIndex (space/canvas index)
├─ /home                     WebsiteHome
├─ /activity                 Activity route
├─ /command-center           Command Center mirror
├─ /new                      Channels-scoped new task
├─ /feeds/:feedId            feed view
├─ /skills                   Channels-scoped skills
├─ /mcp-servers              Channels-scoped MCP servers
└─ /:channelId
   ├─ /                      WebsiteChannelHome
   ├─ /new                   new task in this Space
   ├─ /tasks/:taskId         channel task detail
   ├─ /dashboards/:id        canvas/dashboard detail
   ├─ /canvases              canvases index
   ├─ /context               Space context
   ├─ /history               Space history
   ├─ /loops                 Space loops tab
   └─ /artifacts             Space artifacts
```

The main pane changes for all of these route transitions. The sidebar may remain on the list, however, when the transition came from a Space task row. A direct deep link, mention, notification, keyboard shortcut, or ordinary Space selection opens the Space pane instead.

## Legacy Code sidebar map

Outside the new Channels layout, `SidebarNavSection` is rendered above the task list:

```text
Code sidebar
  ├─ New task ─────────────> /code (or channel-scoped /website route when called in Channels)
  ├─ Search ───────────────> opens command menu in place
  ├─ Inbox ────────────────> /code/inbox
  ├─ Command Center ──────> /command-center
  ├─ Activity ─────────────> /website/activity
  ├─ Configure ───────────> /settings/:category
  └─ Loops ────────────────> /code/loops
```

When the same section is rendered inside Channels, Command Center uses its `/website/command-center` mirror and New task uses the current Space where possible. Inbox and Activity do not have equivalent behavior: Inbox still targets `/code/inbox`, while Activity targets `/website/activity`. This means a click can intentionally move the user from Channels chrome to Code chrome for Inbox.

Visibility and order are controlled by persisted sidebar settings. The rail keeps Home and Spaces pinned, applies the same visibility overrides to customizable items, and places Activity according to rail-specific ordering rather than the legacy section's ordering.

## Startup and restoration

Startup location is persisted per auth identity under `startup-location:v2:{identity}`. On startup:

```text
boot authenticated app
  │
  ├─ saved v2 href exists
  │    └─ restore that href
  │
  ├─ legacy href exists
  │    └─ return it and retry default Space provisioning
  │
  └─ no saved href
       ├─ provision/find personal + general Spaces
       └─ open /website/{generalSpaceId}
```

Every subsequent route change calls `rememberStartupLocation`, so the next launch restores the last URL. The persisted URL stores route state, not the `pane` view state or the `currentChannelId` store. The first-run flow explicitly opens the Space list while keeping the general Space scoped.

## Alerts, badges, and activity

“Alerts” are represented by three rail badge sources:

```text
Activity          <- useTaskActivity().unreadCount
Inbox             <- useInboxAllReports({ ignoreFilters: true }).counts.pulls
Command Center    <- useCommandCenterActiveCount()
```

The rail polls Inbox on a 60-second interval. Activity is a task-activity unread count. Command Center is a neutral count of active command-center items. Clicking a badge follows the same route behavior as clicking the icon; the badge itself does not create a separate alert route.

Activity is special in the Channels layout:

```text
click Activity
  └─ /website/activity
       ├─ ChannelsSidebar becomes ActivityFeedList
       └─ main pane becomes ActivityDetailPane
            └─ selecting an item opens its task/canvas detail in the right pane
```

When Activity is not active, hovering its rail icon opens a preview popover. Once active, the popover is disabled because the feed already occupies the sidebar. This is a useful example of the route controlling both content ownership and interaction affordance.

## What is working well

- Rail selection is derived from the route, preventing a highlight from changing without the large pane changing.
- Spaces selection remembers the currently scoped Space when leaving another destination.
- Space task rows can update the main pane without taking the user away from the list they are browsing.
- Direct channel routes and deep links override the list-preservation latch and open the requested Space pane.
- The scoped Space is validated against the live project channel list and cleared when stale.
- Startup URLs are persisted per identity, and first-run provisioning opens a usable general Space.
- Activity has one route and one owner for the feed, avoiding a duplicate feed in the sidebar and main pane.

## Current asymmetries and likely sources of confusion

1. **Spaces is not a normal destination.** Most rail clicks replace the main route. Spaces may only change the sidebar pane, so users can reasonably interpret a click as “nothing happened” when the main content remains the same.
2. **The selected Space is local state, not URL state.** The URL identifies a Space only for channel routes. On `/website/home`, `/website/activity`, or `/code/inbox`, the current Space can remain scoped invisibly until Spaces is selected.
3. **Inbox exits Channels.** The rail is visually presented as one navigation system, but Inbox routes to `/code/inbox` and therefore removes the Channels rail/sidebar layout ownership. Command Center has a Channels mirror; Inbox does not.
4. **Space task selection intentionally splits state.** The main pane enters the task while the sidebar remains on the list. This is efficient for browsing but differs from clicking the Space row, which slides into the Space pane.
5. **Persistence covers the URL, not the sidebar pane.** A restart restores the last route, but the list/detail slider is initialized separately. The current code comments define a cold scoped Space as the resting state, while first-run explicitly forces the list.
6. **Legacy and Channels entry points are not fully mirrored.** The older sidebar's “New task” and Command Center adapt to Channels; Inbox, settings, scouts, and several Code destinations remain canonical Code routes.

## Product conclusion

The current navigation is not a single stack. It is a route-driven destination system plus a Space-scoped browsing context. The reported behavior is therefore partly expected: clicking a Space row can change only the sidebar because it is a scope selection, while clicking a rail destination should change the main route. The strongest consistency improvement would be to make that distinction visible in the interaction model and then decide which destinations should preserve the Channels context with mirrored routes, especially Inbox.

Before changing behavior, the most valuable product decision is:

```text
Does “select a Space” mean...
  A. browse/select the Space while preserving the current main page, or
  B. navigate the main page into that Space's home every time?
```

The current code implements A for Space rows and a hybrid of A/B for the Spaces rail. Any follow-up fix should preserve the intentional task-row behavior unless the desired experience is explicitly B.

