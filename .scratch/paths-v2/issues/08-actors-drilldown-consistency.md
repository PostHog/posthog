# Actors drill-down consistency

Type: grilling
Status: open
Blocked by: 03

## Question

What does clicking a node or edge show, and how is it guaranteed to match the equivalent funnel's persons?

Decide:

- Drill-down targets: node (all actors reaching step N as X), edge (actors doing A→B at step N), drop-off, "other" bucket — which are clickable and what actor set each returns.
- The actors query implementation: reuse the funnel actors machinery (facts in [Funnels machinery map](02-funnels-machinery-map.md)) vs a paths-v2 actors query — the counts must equal the rendered numbers and the equivalent funnel's drill-down.
- Aggregation-unit interplay: if [Counting semantics](03-counting-semantics.md) picks per-session counting, a "person" modal shows fewer rows than the edge value — how is that displayed honestly?
- v1 gap to close: the tracking issue lists "implement the actors query" as an open todo; v1's modal semantics are part of the numbers-don't-match complaints.
