# MCP analytics dashboard layout

The overview groups usage trends before the harness and model breakdowns, followed by reliability and sessions flagged for review.
The tool calls and errors chart shares a row with the tool call breakdown when the scene is at least 64rem wide.
Both chart areas have matching heights.
Harness and model cards share a row when the scene is at least 48rem wide; narrower scenes stack them.
The error-rate chart and sessions flagged for review also share a row at 64rem.
Both pairs stack below that width to keep chart labels and table columns readable.
These breakpoints follow the scene container, including when a side panel reduces the available space.

Harness and model breakdowns use the same horizontal Quill bar chart treatment.
Both charts use plain bars with a shared scale from zero to all calls in the selected period, so bar lengths agree with the displayed percentages.
Model percentages include unknown calls in their denominator.
The unknown-model percentage sits beside the call count, with the exact count and an explanation in a tooltip.
Both chart regions have a bounded height and scroll when their labels need more space.

The **Show all models** button in the card header opens a dialog with the existing paginated model table.
It keeps the dashboard layout stable while browsing long model names or additional pages.
The harness overview shows the top six named harnesses and groups the remaining calls into **Other harnesses**.
This group includes smaller named harnesses and the backend's unrecognized-client bucket; it does not mean that every call lacks client identity.
**Show all harnesses** opens a paginated table of all returned harness groups, preserving the active dashboard filters.
The table labels the backend's existing **Other** bucket as **Unrecognized harnesses**.
The combined chart row shows a call-weighted error rate and omits sessions, since one session may contain calls from multiple harnesses.
**Explore models** opens the breakdown in an insight with the current filters.

For visual checks, use the dashboard and narrow dashboard stories, plus the harness and model card stories.
Check light and dark themes, laptop windows, and a 520px scene.
Verify that labels stay readable, the two breakdown surfaces match, tiny bars respond to hover, and the model dialog supports pagination and closing.

Run the full scene stories after the narrow story when checking snapshots.
The snapshot runner clears the previous layout class before each capture, so padded component styles cannot shrink later fullscreen scenes.
