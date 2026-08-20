# Memory watchdog

Captures evidence when the app's memory footprint spikes or the app dies, so
"it ballooned again and I had to force quit" arrives with something to look at.

Source: `apps/code/src/main/watchdog/`.

## What it watches

Every 15s it samples resident memory across the **whole process tree**, not just
Electron. That distinction is the point: the workspace-server child and the
agent CLI processes under it are ordinary OS processes, so `app.getAppMetrics()`
never reports them even when they hold most of the memory. The sampler merges
`getAppMetrics()` — which knows each Electron process's role — with `ps` output,
keyed by pid.

## What it captures

A report directory under
`<userData>/diagnostics/reports/<timestamp>-<trigger>/` containing:

- `report.json` — the triggering sample, the samples leading up to it, V8 heap
  statistics, and app/config metadata
- `summary.json` — the small index entry
- `breadcrumbs.jsonl` — a copy of the recent breadcrumb tail
- `*.heapsnapshot` — only when heap snapshots are enabled

Triggers:

| Trigger               | Cause                                                  |
| --------------------- | ------------------------------------------------------ |
| `threshold`           | Total RSS over the threshold for 3 consecutive samples   |
| `render-process-gone` | Renderer crashed or was OOM-killed                       |
| `child-process-gone`  | A GPU or utility process died                            |
| `uncaught-exception`  | Uncaught exception in the main process                   |
| `manual`              | Developer menu → "Capture memory snapshot"               |
| `unclean-shutdown`    | Previous run never reached a shutdown handler            |

## Surviving a force quit

Nothing runs on `SIGKILL`, which is what a force quit and the OOM killer send.
Two mechanisms cover that gap:

1. **Breadcrumbs.** A trimmed sample is appended to
   `<userData>/diagnostics/breadcrumbs.jsonl` on every tick, so the run-up to a
   hard kill is already on disk when it happens.
2. **Session sentinel.** A file is written at startup and removed on a clean
   quit. If it is still there on the next launch, the previous session died
   without warning, and its breadcrumbs are promoted into an `unclean-shutdown`
   report.

Native minidumps for renderer and GPU crashes are separate — `crashReporter`
already writes those to `app.getPath("crashDumps")`.

## Configuration

All optional, all environment variables:

| Variable                                | Default                                | Notes                                       |
| --------------------------------------- | -------------------------------------- | -------------------------------------------- |
| `POSTHOG_CODE_WATCHDOG_DISABLE`         | unset                                  | Turns the whole thing off                    |
| `POSTHOG_CODE_WATCHDOG_THRESHOLD_MB`    | 50% of system RAM, clamped to 2–24GB   | Absolute trip point                          |
| `POSTHOG_CODE_WATCHDOG_INTERVAL_MS`     | `15000`                                | Sample interval                              |
| `POSTHOG_CODE_WATCHDOG_SUSTAINED_SAMPLES` | `3`                                  | Consecutive breaches before capturing        |
| `POSTHOG_CODE_WATCHDOG_COOLDOWN_MS`     | `600000`                               | One report per plateau, not one per sample   |
| `POSTHOG_CODE_WATCHDOG_MAX_REPORTS`     | `10`                                   | Older report directories are pruned          |
| `POSTHOG_CODE_WATCHDOG_HEAP_SNAPSHOTS`  | unset (off)                            | See below                                    |
| `POSTHOG_CODE_WATCHDOG_BREADCRUMB_MB`   | `16`                                   | Breadcrumb log size before rotation          |

Heap snapshots are off by default because writing one is synchronous and
produces a file roughly the size of the heap — capturing a 4GB renderer freezes
the app and writes 4GB. Turn them on when actively hunting a leak.

## Reading a report

`totalRssBytes` sums per-process RSS, so shared pages are counted more than once
and the true footprint is lower than the sum. Use it to see the shape of a spike
and which process owns it, not as an exact figure.

Agent CLI processes cannot be heap-snapshotted from the main process. If a
report points at one, attach a Node inspector to its pid.

Command lines from `ps` are redacted for anything that looks like a credential
before they reach a report.

## Where it lives, and why

The watchdog is plain modules under `apps/code/src/main/watchdog/`, constructed
in `main/index.ts`. It is deliberately not an Inversify service: it has to run
before the container is ready, keep sampling while the app is tearing itself
down, and observe the Electron host's own death. Every Electron surface it needs
(`getAppMetrics`, the renderer heap snapshot, the diagnostics path) is passed in
by the host, so the modules themselves import no Electron and stay testable.

## Known gaps

- Windows has no process-tree enumeration; samples fall back to Electron's own
  metrics and `processTreeAvailable` is `false` in the report.
- Nothing is uploaded. Reports stay on the user's disk and have to be attached
  by hand. Only aggregate counters go to PostHog.
- No in-app UI. Capture and reveal live in the Developer menu.
