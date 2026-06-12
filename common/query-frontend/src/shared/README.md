# Shared

Helpers shared across query node kinds.
Currently this is `mathsLogic`, the taxonomy of aggregation "math" options used by the insight query editors.

## mathsLogic

Every entity in an insight query's `series` carries a `math` field (e.g. `total`, `dau`, `avg`, `unique_group::0`, `hogql`) that says how events are aggregated.
`mathsLogic.tsx` is the single source of truth for what each math option means: its display `name`/`shortName`, a rich `description` tooltip, and a `MathCategory` (`EventCount`, `SessionCount`, `ActorCount`, `EventCountPerActor`, `PropertyValue`, `HogQLExpression`).

The editor surfaces in `../nodes/InsightViz/` (notably the action filter rows and the trends series controls) read these definitions to populate the math dropdown, and summary/tooltip code uses the names to describe series.

### Static definition maps

- `BASE_MATH_DEFINITIONS` — total count, unique users, weekly/monthly active users, unique sessions, first-time events.
- `PROPERTY_MATH_DEFINITIONS` — sum/avg/min/max/median/percentiles over a numeric property.
- `COUNT_PER_ACTOR_MATH_DEFINITIONS` — event counts per user (avg, min, max, ...).
- `HOGQL_MATH_DEFINITIONS` — arbitrary HogQL aggregation expressions.
- `FUNNEL_MATH_DEFINITIONS` — funnel-specific options (any match, first-ever occurrence, first occurrence matching filters).
- `CALENDAR_HEATMAP_MATH_DEFINITIONS` — total count and unique users for the calendar heatmap display.

### The logic

`mathsLogic` is a global (un-keyed) kea logic that combines the static maps with project-dependent state from `groupsModel` and `groupsAccessLogic`:

- `mathDefinitions` — the full merged map shown in the math dropdown.
- `groupsMathDefinitions` — one "unique <group type>" entry per group type defined in the project (e.g. `unique_group::0` → "Unique organizations").
- `funnelMathDefinitions`, `calendarHeatmapMathDefinitions`, `staticMathDefinitions`, `staticActorsOnlyMathDefinitions` — filtered views for specific editor surfaces.

It also exports the conversion helpers `mathTypeToApiValues()` and `apiValueToMathType()`, which translate between the serialized `math` + `math_group_type_index` pair and the combined `MathType` string used in the UI.

`mathsLogic` is an internal implementation detail of the `<Query />` tag's editor surfaces.
Consumers pass `query`/`setQuery` props to `<Query />` and should not bind this logic directly.
