# Polling and intervals

When you need to refresh something on a fixed interval (poll a running job, refresh
a count, tick a clock), do it through `cache.disposables`. The disposables plugin
handles cleanup on unmount and **auto-pauses the interval when the tab is hidden**,
which is almost always what you want for polling.

For the full disposables API see the [using-kea-disposables](../../using-kea-disposables/SKILL.md) skill.
The patterns below are kea-side conventions for the common shapes.

## Why not a bare `setInterval`?

```ts
// don't do this
afterMount(({ actions, cache }) => {
    cache.pollTimer = setInterval(() => actions.loadFoo(), 5000)
}),
beforeUnmount(({ cache }) => clearInterval(cache.pollTimer)),
```

Problems:

- Hidden-tab waste: the interval keeps hitting the API while the user is on a different tab.
- Easy to leak: forget the `beforeUnmount` and the timer outlives the logic.
- No way to stop early on a state change (need to track the timer manually).

The disposables plugin solves all three. The patterns below are just the right shape
for common polling jobs.

## Pattern: poll while a flag is true

Use case: a long-running job, an "active" indicator. The polling lives only as long
as the work it's tracking.

```ts
listeners(({ actions, values, cache }) => ({
    startPolling: () => {
        cache.disposables.add(() => {
            const id = setInterval(() => actions.loadStatus(), 5000)
            return () => clearInterval(id)
        }, 'statusPoll')
    },
    stopPolling: () => {
        cache.disposables.dispose('statusPoll')
    },
    loadStatusSuccess: ({ status }) => {
        if (status === 'finished') {
            actions.stopPolling()
        }
    },
})),
```

**Why the named key (`'statusPoll'`):** calling `startPolling` twice replaces the
previous timer instead of running two in parallel. And `dispose('statusPoll')`
stops it without unmounting the whole logic.

## Pattern: poll while mounted

Use case: a heartbeat / counter that runs the whole time the view is open.

```ts
afterMount(({ actions, cache }) => {
    cache.disposables.add(() => {
        const id = setInterval(() => actions.loadCurrentTeam(), 30000)
        return () => clearInterval(id)
    })
}),
```

**No key needed** — the timer is fire-and-forget; the plugin tears it down on
unmount. The auto-pause on hidden tabs means it costs nothing while the user is
elsewhere.

## Pattern: poll on hover only

Use case: a tooltip / popover that wants live data while the cursor is over it.

```ts
listeners(({ actions, cache }) => ({
    setIsHovering: ({ isHovering }) => {
        if (isHovering) {
            cache.disposables.add(() => {
                const id = setInterval(() => actions.setNow(new Date()), 500)
                return () => clearInterval(id)
            }, 'hoverTick')
        } else {
            cache.disposables.dispose('hoverTick')
        }
    },
})),
```

The key lets the mouseleave handler stop the ticker without unmounting anything.

## Pattern: one-shot timeout that may be spammed

Use case: a "saved!" banner that disappears after 2 seconds; if you save again, the
timer resets.

```ts
listeners(({ actions, cache }) => ({
    showSaved: () => {
        cache.disposables.add(() => {
            const id = setTimeout(() => actions.hideSaved(), 2000)
            return () => clearTimeout(id)
        }, 'savedBanner')
    },
})),
```

Same key on each call — the previous timer is auto-disposed before the new one is
registered. No manual tracking.

## Picking the interval

- **Faster than 1 second**: hover/animation only. Anything API-driven at this rate
  pummels the server.
- **1–5 seconds**: live indicators while the view is open (current online count, hot
  job status).
- **10–30 seconds**: background state refresh while the user is doing something else.
- **Minutes**: stale-data refresh on long-lived pages.

Always include the interval as a named constant near the top of the file
(`REFRESH_INTERVAL_MS = 5000`). It makes the trade-off explicit.

## Anti-patterns

See [anti-patterns.md](anti-patterns.md) for the consolidated catalogue.
