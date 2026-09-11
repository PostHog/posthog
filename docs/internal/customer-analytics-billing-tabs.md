# Account usage and spend tabs

Usage and Spend display saved billing insights in both expanded account rows and the account detail scene.
The account supplies the organization variable, and the date filter supplies the start and end dates.
SQL variable pickers are hidden because these values are controlled by the account tab.

Supported SQL charts render through `AccountBillingChart`. Other visualizations, including series
breakdowns, render through an embedded `Query` in a fixed-height container. Embedded SQL charts fill
that container; standalone SQL insights retain their viewport-based height.
