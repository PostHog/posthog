# Evidence sources

Where to look before you decide a change is worth making, and what each source is good and bad at.
Use more than one: telemetry says what happened, replay says why, tickets say what hurt enough to report.

All of these live in PostHog's own project (project 2 on us.posthog.com).
Use the PostHog MCP (`posthog:execute-sql`, dashboards, vision scanners, conversations) to query them.

## Telemetry

- Events: see [telemetry-contract](telemetry-contract.md) for names and properties.
- Queries: [refreshing-product-reality](refreshing-product-reality.md).
- Live values: the `taxonomic_filter_*` metrics in the data catalog, run with `posthog:data-catalog-metric-run`.
- **Good for:** sizing a problem, before and after.
- **Bad for:** intent.
  A close without a pick can be success (the user only looked) or failure.
- **Watch for:** staff traffic, `groupType` vs `sourceGroupType`, and open-level splits covering engaged opens only.

## The health dashboard

The "Taxonomic filter health" dashboard tracks selection rate, position, empty results and recovery, latency, fetch failures, and the category-then-empty trap.

- **Good for:** trends and spotting regressions after a deploy.
- **Bad for:** causes.
  Some tiles include staff traffic.
  A mean dwell tile is skewed by long idle opens; prefer percentiles.

## Replay Vision scanners

Two scanners watch sampled sessions that open the picker:

- A **classifier** tags each session as success, struggle or abandoned, with reasons and cited moments.
- A **summarizer** describes how the user browsed and picked.

Results arrive as `$recording_observed` events.
Tags are in `scanner_output_tags`, cited moments in `scanner_output_reasoning_segments`.

- **Good for:** why a pattern happens, and failures telemetry misses.
- **Bad for:** exact rates.
  It is a sample, and prompt versions change.
  Compare within one scanner version.
- "Abandoned" often means opened and dismissed.
  Read the reasoning.

## Support tickets

PostHog conversations tickets mentioning the picker, filters or specific property names.

- **Good for:** what customers care about enough to report.
- **Bad for:** prevalence.
  Few people file tickets.
- Recent themes: UI bugs, missing items, wrong category.
  Almost never slowness.

## GitHub issues and pull requests

Search `PostHog/posthog` for "taxonomic", "property filter", and the component paths.

- **Good for:** known bugs, past attempts, and why earlier decisions were made.
- **Bad for:** customer impact.
  Most picker issues are filed by staff.

## Research

Useful published work for picker decisions:

- Nielsen Norman Group: recognition over recall, mode errors, search results behavior.
- Baymard Institute: no-results pages, autocomplete, search scope.
- Furnas et al., "The vocabulary problem in human-system communication" (1987).
- Studies of natural-language and AI interfaces: faster, but less accurate and prone to over-trust.

See [design-principles](design-principles.md) for how these apply.

## Opinions

Issues, Slack threads and people who have worked on the picker carry useful hypotheses.
Treat them as hypotheses.
Several long-held beliefs about this picker turned out to be right in direction and wrong in size when checked against data.
