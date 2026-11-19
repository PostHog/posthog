# Mobile exploration for APM

The `apm-mobile-triage` flag enables compact APM layouts below the shared `lg` breakpoint (992 CSS pixels).
It does not change product access, queries, retention, or saved desktop settings.

## Logs

Search and time controls fit the viewport.
Filters and the volume chart expand on demand, leaving space for results without changing desktop preferences.
Each row shows its timestamp, severity, service, and message preview; tap it to open the full log details and apply attribute filters.
Use the sort button above the list to switch between newest and oldest first.
The page scrolls vertically on short screens, including landscape phones.
At desktop widths, the configured columns return.

## Validation

Use the Logs scene stories with synthetic fixtures: `LogsScene` for the flag disabled and `LogsSceneMobile` for enabled.
Check 320×568, 390×844, 430×932, 844×390, 768×1024, 1024×768, and a desktop viewport.
Verify search, time range, filter expansion, row opening, detail closing, sorting, and scrolling to later results.
Resize across 992 pixels with a saved desktop column configuration and confirm it is preserved.

Tracing and metrics are subsequent slices of this rollout; the shared flag alone does not change their layouts.
