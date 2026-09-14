# MCP analytics dashboard layout

The overview groups usage trends before the harness and model breakdowns, followed by reliability and sessions flagged for review.
Time-series charts use the full scene width.
Harness and model cards share a row when the scene is at least 48rem wide; narrower scenes stack them.
The reliability cards share a row at 64rem.
These breakpoints follow the scene container, including when a side panel reduces the available space.

Harness and model breakdowns use the same horizontal Quill bar chart treatment.
Each track represents all calls in the selected period, so bar lengths agree with the displayed percentages.
Model percentages include unknown calls in their denominator.
Model coverage remains visible below the reported models.
Both chart regions have a bounded height and scroll when their labels need more space.

**Show all models** opens a dialog with the existing paginated model table.
It keeps the dashboard layout stable while browsing long model names or additional pages.
**Explore models** opens the breakdown in an insight with the current filters.

For visual checks, use the dashboard and narrow dashboard stories, plus the harness and model card stories.
Check light and dark themes, laptop windows, and a 520px scene.
Verify that labels stay readable, the two breakdown surfaces match, tiny bars respond to hover, and the model dialog supports pagination and closing.
