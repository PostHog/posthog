---
stamphog:
  size_gate:
    max_lines: 1000
---

Desktop PRs are often tall: one feature usually lands across packages/core, packages/ui and the app in a single PR, so substantive line counts run past the global ceiling without adding review risk.
A larger line count alone is not a red flag here, so it may be reviewed more leniently than the global default.

Correctness concerns get the usual full scrutiny: authentication, data handling, and CI or workflow changes are judged exactly as they are anywhere else.
This guidance only relaxes the line ceiling; it never lowers the bar for the deny rules or the refusal criteria.
