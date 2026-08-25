---
paths:
  - 'tach.toml'
---

This file enforces Python import boundaries. Read
["Extending what crosses a boundary"](../../products/AGENTS.md#extending-what-crosses-a-boundary)
before adding a `depends_on` entry — the fix is usually a facade method, not a new dependency.
