# PostHog Braze Plugin

[![License: MIT](https://img.shields.io/badge/License-MIT-red.svg?style=flat-square)](https://opensource.org/licenses/MIT)

This plugins sends [Braze](https://braze.com) analytics data series to Posthog.

The data series will be imported once a day, for a time window corrisponding to 00:00AM UTC to 12:00PM UTC of the previous day.

Campaigns, Canvases, News Card Feeds and Segments will only be tracked if any activity was recorded in the last 24 hours time window.

## API Key Permissions

Depending on what kind of analytics you want to export from Braze to Posthog, you need to give your API Key the correct permissions.

You can read more about Braze REST Api Key permissions [here](https://www.braze.com/docs/api/api_key/#how-can-i-use-it)

Campaigns:

```
campaigns.list
campaign.data_series
campaigns.details
```

Canvas:

```
canvas.list
canvas.data_series
canvas.details
```

Custom Events:

```
events.list
events.data_series
```

KPIs:

```
kpi.mau.data_series
kpi.dau.data_series
kpi.new_users.data_series
kpi.uninstalls.data_series
```

News Feed Cards:

```
feed.list
feed.data_series
feed.details
```

Segments:

```
segments.list
segments.data_series
segments.details
```

Sessions:

```
sessions.data_series
```

## Plugin Parameters:

-   `Braze REST Endpoint` (required): The REST endpoint where your Braze instance is located, [see the docs here](https://www.braze.com/docs/api/basics)
-   `API Key` (required): Your Braze API Key, [see the docs here](https://www.braze.com/docs/api/api_key/)
-   `Import Campaigns` (required): Toggle [Campaign](https://www.braze.com/docs/user_guide/engagement_tools/campaigns) analytics imports
-   `Import Custom Events` (required): Toggle [Custom Events](https://www.braze.com/docs/user_guide/data_and_analytics/custom_data) analytics imports
-   `Import Canvas` (required): Toggle [Canvas](https://www.braze.com/docs/user_guide/engagement_tools/canvas) analytics imports
-   `Import News Feed Cards` (required): Toggle [News Feed](https://www.braze.com/docs/user_guide/engagement_tools/news_feed) analytics imports
-   `Import KPIs` (required): Toggle KPI imports (Daily New Users, DAU, MAU, Daily Uninstalls)
-   `Import Segments` (required): Toggle [Segment](https://www.braze.com/docs/user_guide/engagement_tools/segments) analytics import
-   `Import Sessions` (required): Toggle Sessions analytics import

## Installation

-   Visit 'Project Plugins' under 'Settings'
-   Enable plugins if you haven't already done so
-   Click the 'Repository' tab next to 'Installed'
-   Click 'Install' on this plugin
-   Fill in required parameters (see above)
-   Enable the plugin
