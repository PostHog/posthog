---
name: context-layer-consolidation
description: Keep the context wiki's structure coherent as pages accumulate
---

# Context layer consolidation

After synthesizing new material, spend a bounded pass keeping the wiki coherent. This runs on the same `dream/<date>` branch, before publishing.

## What to do

- Evolve AGENTS.md's map as pages appear or move, so it stays an accurate entry point.
- Merge near-duplicate pages; leave a wikilink from the merged-away name's callers.
- Resolve recorded disagreements you now have evidence to settle; note the resolution and its source.
- Split a page that has grown past one topic; keep the hub page linking to the parts.
- Fix broken wikilinks by writing the missing page when you have material, or leaving the link when you don't.

## Limits

- Structure edits stay inside the default directories; `scripts/lint` is the arbiter.
- Do not delete content you cannot place; move it to the page it belongs to.
- Keep this pass small relative to synthesis: coherence, not rewrites.
