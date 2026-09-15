# Account usage and spend tabs

Usage and Spend display saved billing insights in both expanded account rows and the account detail scene.
The account supplies the organization variable, and the date filter supplies the start and end dates.
SQL variable pickers are hidden because these values are controlled by the account tab.

Supported SQL charts render through `AccountBillingChart`. Other visualizations, including series
breakdowns, render through an embedded `Query` in a fixed-height container. Embedded SQL charts fill
that container; standalone SQL insights retain their viewport-based height.

The Usage tab offers Daily, Weekly, and Monthly aggregation. Daily is the default.
Weekly buckets start on Monday; monthly buckets start on the first day of the month.
Each bucket sums only the daily usage inside the selected date range, so edge buckets can be partial.
The tab groups the existing saved query's date and value columns without changing the saved insight.
Spend insights retain their existing monthly calculations.

Usage queries request up to 10,000 buckets so year-to-date ranges are not cut off by SQL table pagination.
Automatic usage charts use the account chart renderer, with date-axis tick spacing and wrapping series
controls outside the fixed-height plot. The interval and date controls wrap in narrow containers.
The selected interval survives tab switches while the account remains open.
