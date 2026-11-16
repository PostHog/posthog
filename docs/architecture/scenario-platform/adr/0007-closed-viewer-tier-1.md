# Viewer contributions are data in a closed form; no adapter code is served

An adapter contributes to the run viewer in two tiers:

- **Tier 0:** named series with labels.
- **Tier 1:** panel specs and node looks in its manifest's `view`. Templates and predicates have a closed form: a series against a constant or another series, `any` and `all`, typed line parts, a fixed set of formats, and a closed enum of node states.

Core owns the verdict, the end-to-end panels, the valve timeline, stale and stopped rendering, the default per-process panels, and composition by card order.

A code slot (tier 2, `render(root, ctx, t)`) is named in the spec but not built, and the viewer serves no adapter code. A closed form can be loaded from another team's manifest without a viewer review and needs no `eval`. Every extension of it ships only with a Workflows page element that needs it.

The trade-off is that a team wanting a novel widget waits for tier 2. That trigger is a named widget tiers 0 and 1 cannot draw.
