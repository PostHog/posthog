# MCP Analytics activity counts

The Activity banner summarizes a fixed 30-day window. Its call count, client count, favorite tool, and failures come from the activity overview.
The lifetime onboarding signal only selects the first-call copy. A project with older calls and no recent activity sees no calls in the banner.

The live activity table defaults to 30 days. Changing its date range does not change the banner's window.
Shared property and internal-user filters apply to both the table and the banner.
Changing a shared filter clears the previous overview while its replacement loads. A failed load shows a retry action.
Filtered Activity shows individual intents because the AI digest summarizes unfiltered sessions.

Event count queries preserve selected event names and date ranges. The total removes property and `where` filters; the matched count retains them.
Both counts retain fixed properties that scope the table.

Session filters select matching tool calls without moving session bounds inside the bounded scan.
The scan includes seven extra days on each side of the selected range. Longer sessions can have clipped bounds and totals.
If session details fail to load, a retry action replaces the loading indicator and hides calls from previous filters.
Tool-neighbor reports keep the full conversation sequence when finding the calls before and after a match.
