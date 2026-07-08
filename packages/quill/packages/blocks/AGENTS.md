# Blocks — Agent Reference

`@posthog/quill-blocks` is the product-level patterns layer of quill (tokens > primitives > components > blocks). It is currently an empty placeholder — `src/index.ts` exports nothing so downstream `export *` re-exports keep working while the layer is unimplemented.

Do not add components here without checking the layering: reusable UI built only on Base UI belongs in `primitives`; compositions of primitives with logic (data wiring, state machines) belong in `components`; blocks are reserved for opinionated, product-shaped patterns (page headers, settings panels, command palettes).

When the first block lands, replace this file with a consumer guide following the structure of `../primitives/AGENTS.md`.
