# PostHog Desktop navigation map

Date: 2026-08-22  
Scope: `products/desktop` renderer routing and Channels/Spaces navigation.

## 1. Shell

TanStack Router owns the main content route. The root layout owns the title bar,
rail, sidebar, and route outlet.

```text
┌──────────┬──────────────────────┬──────────────────────────────────────────┐
│ NavRail  │ ChannelsSidebar      │ route outlet                             │
│          │                      │                                          │
│ Home     │ Space list           │ /website/...                             │
│ Spaces   │ OR Space detail      │ /code/...                                │
│ Activity │ OR Activity feed     │ /command-center                          │
│ Inbox    │                      │ /settings/...                            │
│ Command  │                      │                                          │
│ Loops    │                      │                                          │
└──────────┴──────────────────────┴──────────────────────────────────────────┘
```

Source: [`__root.tsx`](../packages/ui/src/router/routes/__root.tsx:280).

When the Channels layout flag is off, the rail is absent. The sidebar uses the
legacy Code navigation section and task list. Settings uses a full-page shell.

## 2. Rail routing

The rail is defined in [`railDestinations.ts`](../packages/ui/src/features/canvas/components/railDestinations.ts:82).
Every destination except Spaces performs a route navigation.

```text
rail click
  │
  ├─ Home            -> /website/home
  ├─ Spaces          -> showSpaceList() plus conditional route navigation
  ├─ Activity        -> /website/activity
  ├─ Inbox           -> /code/inbox
  ├─ Command Center  -> /website/command-center
  └─ Loops           -> /code/loops
```

The selected rail item is derived from the deepest route match. The mapping is
in [`railPane.ts`](../packages/ui/src/features/canvas/railPane.ts:25).

```text
deepest route
  │
  ├─ /website/home*             -> Home
  ├─ /website/activity*         -> Activity
  ├─ /website/command-center*  -> Command Center
  ├─ /command-center*           -> Command Center
  ├─ /code/inbox*               -> Inbox
  ├─ /code/loops*               -> Loops
  └─ all other routes           -> Spaces
```

Therefore channel home, channel task, canvas, context, artifacts, history, and
the `/website` index all select Spaces.

## 3. Spaces navigation state

Spaces uses three independent values:

```text
URL route             = main content
currentChannelId      = selected/scoped Space
channelPaneStore.pane = sidebar view: "list" | "channel"
```

The sidebar keeps both panes mounted. The inactive pane is inert.

```text
currentChannelId = A, pane = channel
              │ showChannelList()
              ▼
currentChannelId = A, pane = list
              │ showChannelPane()
              ▼
currentChannelId = A, pane = channel
```

Source: [`channelPaneStore.ts`](../packages/ui/src/features/canvas/stores/channelPaneStore.ts:3).

### Spaces rail click

```text
click Spaces
  │
  ├─ showChannelList()
  │
  ├─ current rail pane = Spaces
  │    └─ stop; route and main content stay unchanged
  │
  └─ current rail pane != Spaces
       ├─ currentChannelId exists
       │    ├─ latch list for that Space
       │    └─ navigate /website/{currentChannelId}
       └─ no currentChannelId
            └─ navigate /website
```

Source: [`showSpaces()`](../packages/ui/src/features/canvas/components/railDestinations.ts:62).

This is the case where clicking the rail can change only the sidebar: the app
is already on a Spaces route, so no route transition is required.

### Space row click

```text
Space list + click Space A
  ├─ showChannelPane()
  ├─ set currentChannelId = A
  └─ Channels layout: no route navigation
       ├─ sidebar changes to Space A
       └─ main content stays unchanged
```

Implementation: `useOpenChannel()` in [`ChannelsList.tsx`](../packages/ui/src/features/canvas/components/ChannelsList.tsx:1338).

### Space task row click

```text
Space list + click Task T under Space A
  ├─ set currentChannelId = A
  ├─ latch list for A
  ├─ navigate /website/A/tasks/T
  └─ main content changes to task T
       sidebar remains on the Space list
```

Implementation: `useOpenSpaceTask()` in [`ChannelsList.tsx`](../packages/ui/src/features/canvas/components/ChannelsList.tsx:1299).

### Route-to-sidebar synchronization

[`ChannelRouteSync.tsx`](../packages/ui/src/features/canvas/components/ChannelRouteSync.tsx:25)
handles channel routes:

```text
route has channelId
  ├─ set currentChannelId from route
  ├─ matching list latch exists? -> preserve list
  └─ otherwise                    -> show channel pane

route has no channelId
  └─ clear list latch
```

Direct links, mentions, notifications, keyboard shortcuts, and ordinary Space
selection therefore open the channel pane. A task selected from the Space tree
preserves the list by design.

## 4. Route tree

```text
/website
├─ /                         Space/canvas index
├─ /home                     Home
├─ /activity                 Activity
├─ /command-center           Command Center mirror
├─ /new                      Channels new task
├─ /feeds/:feedId            Feed
├─ /skills                   Skills mirror
├─ /mcp-servers              MCP mirror
└─ /:channelId
   ├─ /                      Space home
   ├─ /new                   New task in Space
   ├─ /tasks/:taskId         Task detail
   ├─ /dashboards/:id        Canvas detail
   ├─ /canvases              Canvas list
   ├─ /context               Space context
   ├─ /history               Space history
   ├─ /loops                 Space loops
   └─ /artifacts             Space artifacts

/code
├─ /                         New task
├─ /inbox                    Inbox
├─ /agents                   Agents and Scouts
├─ /loops                    Loops
├─ /archived                 Archived tasks
├─ /tasks/:taskId            Task detail
└─ /pr                       Pull request detail
```

Navigation functions are centralized in [`navigationBridge.ts`](../packages/ui/src/router/navigationBridge.ts:43).

## 5. Legacy sidebar routing

[`SidebarNavSection.tsx`](../packages/ui/src/features/sidebar/components/SidebarNavSection.tsx:59)
provides the legacy Code sidebar and is also reused by the older Channels mode.

```text
New task       -> /code, or channel-scoped /website route
Search         -> command menu; no route change
Inbox          -> /code/inbox
Activity       -> /website/activity
Command Center -> /command-center, or /website/command-center in Channels
Configure      -> /settings/:category
Loops          -> /code/loops
```

Inbox and Loops have no Channels mirror in this navigation layer, so they leave
the Channels route family. Command Center and new task have Channels variants.

## 6. Startup restoration

[`startupLocation.ts`](../packages/ui/src/shell/startupLocation.ts:61) persists
the last URL per authenticated identity.

```text
startup
  │
  ├─ saved startup-location:v2:{identity}
  │    └─ restore saved href
  ├─ legacy startup location
  │    └─ restore legacy href and retry provisioning
  └─ no saved location
       └─ provision/find general Space -> /website/{generalSpaceId}
```

The URL is persisted. `currentChannelId` and `channelPaneStore.pane` are not
persisted by startup restoration. The first-run path explicitly scopes the
general Space and opens the Space list.

## 7. Badges and alerts

```text
Activity         <- useTaskActivity().unreadCount
Inbox            <- useInboxAllReports().counts.pulls
Command Center   <- useCommandCenterActiveCount()
```

The rail refreshes Inbox counts every 60 seconds. Badge clicks use the same
route handlers as icon clicks.

```text
Activity route: /website/activity
  ├─ Channels layout: sidebar = ActivityFeedList
  └─ main pane     = ActivityDetailPane

non-Activity route
  └─ Activity rail hover = preview popover
```

Source: [`NavRail.tsx`](../packages/ui/src/features/canvas/components/NavRail.tsx:172)
and [`activity.tsx`](../packages/ui/src/router/routes/website/activity.tsx:8).

## 8. Navigation invariants

```text
rail selected state       <- route
main content               <- route
selected Space             <- currentChannelId
Space sidebar pane         <- channelPaneStore.pane
startup restoration        <- persisted URL
Space tree expansion       <- persisted space-tree store
```

The implementation intentionally permits one navigation action to update only
sidebar view state: selecting Spaces while already on a Spaces route, or
selecting a Space row in the Space list. All other primary rail selections
change the main route.

