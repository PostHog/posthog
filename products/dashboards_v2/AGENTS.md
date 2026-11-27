# Dashboards v2 agent guide

Dashboards v2 is a set of primitives that a host composes: grid, tiles, sections, tabs, panels, filters and the time range picker.
The `/dashboard-v2` scene, behind the `dashboards-v2` feature flag, is one host.
Other products, such as APM and web analytics, compose the same primitives on their own pages.

## Read the guide for your area first

Topic rules live in [`.agents/`](.agents/).
Before you write or review code in an area below, open its guide.
Each row is the only place that says when to read a guide, so a new guide gets a new row here.

| Guide                                            | Read it before you write or review                                                                  |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| [.agents/primitives.md](.agents/primitives.md)   | Any file under `frontend/`, or a change to what one primitive imports from another or from the host |
| [.agents/performance.md](.agents/performance.md) | A change to how tiles, panels or the grid render, what a context holds, or when a query runs        |
