# MCP Analytics activity counts

The Activity banner summarizes the activity overview's fixed 30-day window. Its
call count, client count, favorite tool, and failures all come from that overview.
The lifetime onboarding signal only determines whether to show first-call copy;
it does not replace the 30-day count. A project with older calls and no recent
activity sees "No tool calls in the last 30 days".

Property filters and the internal/test-user switch apply across the Dashboard, Tool quality, Sessions, and Activity tabs, including tool reports and session details.
They persist in the URL when switching tabs, opening a detail view, or refreshing the page.
The switch follows the project's default until the user sets an explicit value.

Date ranges remain specific to each tab.
The live activity table defaults to 30 days, and changing its date range does not change the banner's window.
Shared property and internal/test-user filters apply to both the table and the banner.
Event count queries preserve the selected event names and date range. The total
removes property and `where` filters; the matched count retains them. Both retain
fixed properties that scope the table.

The activity table labels counts and pagination as "tool calls". Its toolbar
stays fixed while results scroll through LemonTable's content scroll support.
Other DataTable consumers opt into this behavior through
`QueryContext.dataTableAllowContentScroll` and can customize count and pagination
nouns through `QueryContext.dataTableNouns`.

Session filters select matching tool calls while preserving the full session's start and end times.
Tool-neighbor reports keep the full sequence of calls when finding the calls before and after a match.
The Sessions AI digest is hidden while shared filters are active because the digest summarizes unfiltered sessions.
