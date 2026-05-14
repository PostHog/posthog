---
theme: default
title: ph
class: text-center
drawings:
  persist: false
transition: slide-left
---

# `ph`

<div class="mt-6 text-white">
  A CLI for PostHog — friendly to both <b>humans</b> and <b>agents</b>.
</div>

---

# `ph --help`

```bash
Work with PostHog from the command line.

ph <command> [options]

Commands:
  ph auth                Authentication commands
  ph livestream          Stream live events (interactive TUI or JSON)
  ph feature-flags       Manage feature-flags
  ph cohorts             Manage cohorts
  ph insights            Manage insights
  ph dashboards          Manage dashboards
  ph experiments         Manage experiments
  ph persons             Manage persons
  ph events              Manage events
  ph session-recordings  Manage session-recordings
  ph web-analytics       Manage web-analytics
  …33 more
  ph api <method> <path> Make direct API calls
```

<div class="mt-4 text-white">
  Same shape everywhere: <code>ph &lt;group&gt; &lt;verb&gt;</code> — <code>list</code>, <code>view</code>, <code>create</code>, <code>update</code>, <code>delete</code>.
</div>

---

# `ph insights --help`

```bash
ph insights

Manage insights

Commands:
  ph insights list             Get all insights
  ph insights view             Get insight
  ph insights query            Run a saved insight's query and return results
  ph insights create           Create insight
  ph insights update           Update insight
  ph insights delete           Delete insight
  ph insights activity         Get insight activity log
  ph insights recent-activity  Get recent insight activity across the project
  ph insights trending         Get most-viewed insights
```
