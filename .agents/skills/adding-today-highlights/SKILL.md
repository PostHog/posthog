---
name: adding-today-highlights
description: Add a "For you today" highlight source, the rule that turns a product's facts into items on the Today home page (firing alerts, flags that lose reach, ticket SLA breaches, workflow failures). Use when asked to "add a Today highlight", "show X in For you today", "surface X on the home page", or when changing an existing source's query, thresholds, copy or icon. Covers where the rule and its declaration live, the Today facade contract, scopes, caching, ranking inputs, tests, tach, and the frontend icon.
---

# Adding a Today highlight source

Today ranks facts that other products find and shows the best few in "For you today".
The product that owns the data owns its source: the query, the thresholds, and the copy.
Today owns the contract, the ranking, the shared helpers, and its own pulse (routine and key-metric tiles, pinned numbers, home dashboard).

**A source lives in its own product, never in `products/today/`.**
Today has no list of sources to edit. It finds each product's declaration by module name.

## Steps

1. Write the rule in the product's internals, for example `products/<x>/backend/today_highlights.py`, or a package of that name when the product has several sources.
   The rule takes a `HighlightContext` and returns `HighlightFindings`.
   Read the facts through the product's own code. Read other products only through their facades.
2. Declare it in `products/<x>/backend/facade/today_highlights.py`:

   ```python
   """<Product>'s sources for the "For you today" list. Today finds this module by name."""

   from products.today.backend.facade.contracts import HighlightSource

   from ..today_highlights import find_stale_things

   HIGHLIGHT_SOURCES = (HighlightSource(name="stale_things", find=find_stale_things, scopes=("thing:read",)),)
   ```

3. Add `"products.today"` to the product's `depends_on` in the root `tach.toml`, with a `# Facade-only:` comment like the other products have. Today gets no new dependency.
4. Test the rule in the product with `products.today.backend.facade.testing.highlight_context`.
   `products/alerts/backend/tests/test_alert_today_highlights.py` is a short example.
   A test folder without `__init__.py` needs a product-specific file name, so pytest does not collide on `test_today_highlights.py`.
5. The row icon comes from the product. If `PRODUCT_ICONS` in `frontend/src/scenes/project-homepage/today/todayRowIcons.tsx` has no entry for the product yet, add one. That file is Today's, so team-surfaces reviews it.

`products/feature_flags/backend/today_highlights.py` is a complete source with a reach drop and a cleanup item.

## Contract

Import only from Today's facade:

- `facade/contracts.py`: `HighlightCandidate`, `HighlightFindings`, `HighlightContext`, `HighlightSource`, `HighlightMetric`, `DailyValueNotReady`
- `facade/enums.py`: `HighlightLabel`, `HighlightUnit`, `HighlightInterval`
- `facade/highlight_helpers.py`: number and text formatting, `uses_product`, and trend detection

Rules that are easy to get wrong:

- **The source name is a stable key.** Today stores results and analytics under it, so a rename breaks them. The registry raises when two products use the same name.
- **`scopes`** lists the API scopes the viewer needs. Today skips the source when the viewer's scopes or access controls do not cover them.
- **`context.daily(name, compute)`** caches one value per team, property restrictions and day, and every viewer with the same restrictions shares it. Never compute a per-viewer value there. Prefix `name` with the source name.
- **`context.guard(name, provider, default)`** records a failure and returns the default instead of failing the whole list. Use it around each call that can fail on its own.
- Raise `DailyValueNotReady` when a value the source needs is still computing. Today retries the source soon.

## Ranking inputs

Each `HighlightCandidate` carries what Today ranks on:

- `label`: `risk` when something got worse or broke, `opportunity` when the person can act to gain.
- `importance` from 0 to 1, and `relevance` from 0 to 1 for how much this viewer cares. Compare with existing sources before you pick a number: suspended email sending is 0.95, a firing alert 0.85, a flag that lost reach 0.6, a cleanup suggestion 0.3.
- `family`: Today shows at most two items of one family.
- `ref`: items of different families that share a ref are about the same object, so Today shows one of them.
- `key`: stable for the same fact on the same day, for example `flag_reach_drop:<id>`.

Copy follows `/writing-user-facing-copy`: one sentence with numbers in `title`, the comparison and the next action in `detail`.

## Limits

- A row looks the same for every source. A source that needs its own row or preview still needs a change in Today's frontend.
- Only Today's own pulse tiles can be pinned.
