# MCP Analytics activity counts

The Activity banner summarizes the activity overview's fixed 30-day window. Its
call count, client count, favorite tool, and failures all come from that overview.
The lifetime onboarding signal only determines whether to show first-call copy;
it does not replace the 30-day count. A project with older calls and no recent
activity sees "No tool calls in the last 30 days".

The live activity table defaults to 30 days, but its date and property filters
apply only to the table. Changing them does not change the banner's window.
Event count queries preserve the selected event names and date range. The total
removes property and `where` filters; the matched count retains them. Both retain
fixed properties that scope the table.

The activity table labels counts and pagination as "tool calls". Its toolbar
stays fixed while results scroll through LemonTable's content scroll support.
Other DataTable consumers opt into this behavior through
`QueryContext.dataTableAllowContentScroll` and can customize count and pagination
nouns through `QueryContext.dataTableNouns`.
