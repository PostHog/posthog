# Changelog

### 1.30.0 - Wednesday 17 November 2021

-   **Fresh new look-and-feel**. PostHog just got a lot fresher! We have a brand new UI and layout that had been in the works, codenamed `lemonade` (because it's fresh). It's not only a new coat of paint - we've also pushed a lot of improvements to overall navigation and performance too. We call it turbo mode.
-   **Correlation analysis**. Want to understand why users convert or churn? Presenting: Correlation analysis. This nifty new insight automatically matches funnels to any relevant conversion signals, giving you effortless correlation information such as "Users in Canada are 5x more likely to convert" or "Users in Chrome are 3x less likely to convert". This is a very powerful which enables you to take funnel optimization to the next level.
-   **Saved insights**. Tired of creating the same insights multiple times? You can now save insights on PostHog without adding them to a dashboard. Further, you're able to see, search and filter a list of insights created by other team members - which makes it a lot easier to collaborate with PostHog.
-   **Fully revamped recordings**. The recordings playback experience just got a lot better. From significant performance improvements (you'll no longer need to wait for the entire recording to load), to a brand new playback interface. Find the right spot in a recording quickly and understand better what your users are doing.

### 1.29.1 - Monday 25 October 2021

-   Fixes locking migration that would cause the upgrade progress to 1.29.0 to halt (see PR #6640 for details).

### 1.29.0 - Thursday 21 October 2021

-   Explore and deep dive with Paths. We fully revamped our Paths feature to help you explore the actions your users are taking. From jumping from a conversion drop-off in a funnel to identifying Paths ending in a desired action, you will be able to fully understand the paths of your users. We're introducing a lot of additional features such as: select up to 20 steps, fined-grained controls on what paths to show, and grouping paths through wildcards.
-   Multivariate support in feature flags. You will now be able to create feature flags with multiple variants to allow for more comprehensive testing and feature releasing.
-   Private projects. Extra concerns on privacy or compliance? Private projects now lets you have projects to which only certain members of your team have access.
-   Trailing DAU/WAU/MAU graphs. If you're interested in better measuring your user engagement DAU/WAU, WAU/MAU & DAU/MAU ratios can provide great signals.
-   Plus 350+ improvements and fixes, read more in the PostHog Array: https://posthog.com/blog/the-posthog-array-1-29-0

### 1.28.1 - Monday 27 September 2021

-   Bug fix. Fixes a bug where refreshing dashboards could cause a server overload (#5865).
-   Bug fix. Fixes a bug where SAML wouldn't work correctly on Dockerized installations (#5965).
-   Bug fix. Adds more safeguards to prevent incorrect person merges, leading to incorrect user counts (#6023). In addition, we now report an aggregate number to signal if any incorrect data is detected (#6024).
-   Improvement. Updates event reporting to enable usaged-based billing for Scale customers.

### 1.28.0 - Wednesday 15 September 2021

-   Significantly revamped performance. When running on OSS Clickhouse, we now automatically create during weekends columns for event and person properties to speed up queries. This can speed up your slower queries 2-25x.
-   Advanced engagement cohorts. Create automatic user cohorts based on actions performed by users in the last N days (e.g. to identify power users).
-   SAML support. Users with an Enterprise license can now enable SAML authentication and user provisioning.
-   Advanced funnel building. More features to build more detailed funnel views, such as custom step ordering, event exclusions, among others.
-   300+ improvements & fixes across the app
-   **❗️Breaking Change**. The previously deprecated `/api/user/` endpoint has **been removed.** See https://posthog.com/docs/api/user for details on how to update.
-   **❗️Breaking Change**. Support for Python 3.7 is dropped in this version. Please use Python 3.8 or Python 3.9

### 1.27.0 - Monday 26 July 2021

-   New Funnels Experience.
    -   Funnels have a new bar-chart visualization and show more comprehensive metrics. You can now choose whether to display conversion rates for the full funnel or from each step to the next.
    -   Breakdowns are now supported on funnels! This allows you to identify how user and event properties (for instance, browser or referral source) affect your conversions.
    -   Clicking on a funnel step will reveal a list of persons who have continued or dropped off at that step. From there, you can easily view their sessions (provided you have Session Recording enabled) to find unknown problems or opportunities that would otherwise be hidden in the data.
    -   Going beyond averages, the new **Time to Convert** view shows a distribution of time spent between steps or for the whole funnel.
-   Revamp of legend table & insight tooltips.
    -   The legend table for Insights has received a major styling revamp, including nicer formatting for dates and numbers and clearer identification of breakdown values.
    -   New tooltips allow you to scan and compare multiple values at a glance.
-   New filter experience.
    -   It's now easier than ever to find the event, user, or cohort definitions you're looking for when adding a filter to a query. This change also causes Insights to load significantly faster.
-   Clickhouse is now free to use!
    -   We have ironed out all the details and have now decided to make the Clickhouse backend **fully free** now, no longer requiring a license nor having any additional restrictions. This comes from our commitment to supporting teams and companies of any size, so you can continue using PostHog for free even if your event volume increases significantly.
    -   Clickhouse is deployed a bit differently than our traditional deployment options, you can find full deployment instructions in https://github.com/PostHog/charts-clickhouse/
-   400+ improvements & fixes across the app
-   **DEPRECATED**. The `/api/user` endpoint has [been deprecated](https://posthog.com/docs/api/user#user--deprecated) for a while and will be removed on the next version (1.28.0).

### 1.26.0 - Tuesday 15 June 2021

-   Feature flags for Node.js and Go

-   [Node.js](https://github.com/PostHog/posthog-node/pull/29)
-   [Go](https://github.com/PostHog/posthog-go/pull/2)

You requested and we delivered!

`posthog-node` and `posthog-go` now both support feature flags. [Ruby](https://github.com/PostHog/posthog-ruby/pull/6) and [PHP](https://github.com/PostHog/posthog-php/pull/12) are coming next.

We're making our libraries world-class, and this cycle also saw significant improvements to `posthog-python`, `posthog-js`, and `posthog-flutter`. We now have a dedicated team responsible for our libraries, so expect development to speed up!

Thank you to everyone in the community for supporting us with feature requests and PRs.

-   [Funnel trends](https://github.com/PostHog/posthog/pull/4419)

![Funnel Trends](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/funnel-trends.png)

Following a few refactors, funnel trends are now available in beta for Cloud and self-hosted [Scale](https://posthog.com/pricing) users.

Funnel trends let you see how conversion in a funnel changes over time, as well as specify the time taken between steps for a conversion to be counted.

-   [CSV download for users in a datapoint](https://github.com/PostHog/posthog/pull/4175)

![CSV Download](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/csvexport.png)

If you didn't already know, almost all datapoints in PostHog's 'Insights' section are clickable and reveal the users that make up that datapoint.

Well, now those users can be exported in CSV format, so you can use them in other tools or even create a static PostHog cohort from them.

Thanks a lot for building this [c3ho](https://github.com/c3ho)!

-   [Request retries for posthog-js](https://github.com/PostHog/posthog-js/issues/199)

Continuing on the libraries theme, a much-requested feature is now live for `posthog-js`: retries!

Requests that fail because of for example, the client's network connection, will now be retried up to 10 times within an hour, making sure you miss as few events as possible. So if your user's internet goes down and comes back up, you'll still receive the events that happened when they were offline.

Also, Neil fixed a bug that sent requests to a wrong endpoint (with no impact on tracking). You can read about how Neil solved this issue on his [blog](https://neilkakkar.com/debugging-open-source.html).

-   New plugins for Redshift, PostgreSQL, Salesforce, and PagerDuty

We've just released 4 new integrations with major platforms to enhance your PostHog experience.

Export data to Redshift, Postgres, and Salesforce, and leverage the PagerDuty plugin to get alerts when metrics in PostHog cross thresholds you specify.

-   New querying experience

![New querying experience](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/new-querying.png)

We've redesigned and significantly improved the performance of the query builder in PostHog 'Trends'!

Let us know what you think about it on [Slack](https://posthog.com/slack).

### 1.25.0 - Thursday 13 May 2021

-   100x more, for free

We have increased our free volume on [PostHog Cloud](app.posthog.com) to 1 million events per month for free, instead of the previous 10k.

That means your next PostHog Cloud bill will be up to 225\$/month cheaper!

It's important to us that you have enough room to determine if PostHog is the right fit for you, before committing to the platform.

This change is also retroactive, so existing PostHog users have already had this change applied to their accounts.

Enjoy!

-   [Legends for charts in 'Trends'](https://github.com/PostHog/posthog/pull/3434)

![Legends](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/legends.png)

This feature isn't new to all of you, because we've been testing it out with a [feature flag](https://posthog.com/docs/tutorials/feature-flags). However, legends for charts in 'Trends' are now enabled for everyone!

With legends, you're able to determine with more clarity the different sections/lines you see on a graph, see the exact values for each datapoint, and disable sections with one click. You can find them under your graph in 'Trends'.

-   [Plugin Logs](https://github.com/PostHog/posthog/pull/3482)

![Plugin Logs](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/plugin-logs.png)

Plugins are now able to use the JavaScript `console` API to specify errors that will be shown to users in the PostHog UI. This makes it easier to both debug your own plugins as a developer, and understand what's wrong about your configuration as a plugin user.

-   [Lifecycle Toggles](https://github.com/PostHog/posthog/pull/3961)

![Lifecycle Toggles](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/lifecycle-toggles.png)

Li joined us this cycle and started making an impact from day 1!

As a result of her work, you can now toggle different sections of lifecycle graphs on and off, in order to dig into the metrics that matter most to you.

This change also came with an addition of more in-product hints about the lifecycle functionality.

-   [Resizable Table Columns](https://github.com/PostHog/posthog/pull/3927)

![Resizable Columns](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/resizable-columns.png)

Sam is another one of our new team members who's been smashing it from the moment he joined!

This cycle, in addition to picking up a variety of product fixes and improvements, he also shipped resizable columns for our tables, allowing you to easily get more details from an event, session, or feature flag without having to click on it.

-   [Job queues for plugins](https://github.com/PostHog/plugin-server/pull/325)

Plugins keep getting more and more powerful every new release, and this cycle was no exception.

Plugin developers can now leverage job queues to implement a variety of asynchronous tasks, including retry mechanisms.

In addition, plugins can now leverage have two more functions: `onEvent` and `onSnapshot`.

These are read-only functions that run on processed events and are particularly useful for export plugins. `onSnapshot` handles session recording events while `onEvent` handles all other events.

For more information about this, check our [_Building Your Own Plugin_ page](https://posthog.com/docs/plugins/build).

-   [Fuzzy search for properties](https://github.com/PostHog/posthog/pull/4091)

In addition to making significant changes to improve the experience of users with massive amounts of event names and properties, we have also implemented fuzzy search for properties.

This means that to find a property on a filter, you no longer have to type an exact subset of its name, as our search mechanism will still be able to identify what you mean even if you have a few typos or forgot the _exact_ name of the property.

### 1.24.0 - Wednesday 14 April 2021

-   [GeoIP plugin for all](https://github.com/PostHog/posthog/pull/3894)

![GeoIP](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/geoip.png)

Plugins are now live on PostHog Cloud, and, as a bonus, we have now added out-of-the-box support for the PostHog GeoIP plugin, which adds location properties to your events, such as country and city, as well as a dozen other values!

The plugin works on both cloud and self-hosted installations (`1.24.0` minimum).

-   [New 'Cohorts' tab on person pages](https://github.com/PostHog/posthog/pull/3744)

![Cohorts tab](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/person-cohorts.png)

When viewing a person's page in PostHog, you can now toggle between a view of their properties and a view of the cohorts this person is in, giving you a lot more context on the user you're looking at.

-   [Toolbar support for custom data attributes](https://github.com/PostHog/posthog/pull/3761)

![Data attr](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/data-attr.png)

To make the experience of using the PostHog toolbar better, we have recommended that you set `data-attr` on your elements, so that the toolbar can leverage it for finding elements. However, since a lot of our users already used their own data attributes, we now support adding a list of your own data attributes for the toolbar to look for.

You can configure this in 'Project Settings'.

-   [Dashboard collaboration features](https://github.com/PostHog/posthog/pull/3756)

![Dashboard collab](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/dashboard-collab.png)

Our dashboards keep getting better with every new release, and this one is no different!

Dashboards now support descriptions and tags, making it easier for teams to collaborate when creating internal analytics reports.

These are enterprise features available to our paying Cloud customers, and to enterprise self-hosted users.

If you're interested in having these features on your self-hosted PostHog instance, contact us on <i>sales@posthog.com</i>.

-   [S3 export plugin](https://posthog.com/plugins/s3-export)

We have a new plugin that sends PostHog events to an S3 bucket.

The plugin works on both PostHog Cloud and self-hosted installations (`1.24.0` minimum) - [check it out here](https://posthog.com/plugins/s3-export).

-   [Session recording for heavy websites](https://github.com/PostHog/posthog/pull/3705)

If you tell Karl you found an issue with session recording, he will fix it.

Such was the case with session recording for heavy websites (e.g. those with a lot of images/CSS). We were failing to process large snapshots, leading users of these websites unable to get many session recordings.

This is now fixed - expect a lot more recordings available to you from now on!

-   [New configuration options for posthog-js](https://github.com/PostHog/posthog-js/pull/209)

Following user requests, there are now 10 new config options for `posthog-js`, allowing you to use autocapture with greater privacy for your users, as well as tailor session recording configuration.

The new options are:

-   `mask_all_text`: Specifies if PostHog should capture the `textContent` of autocaptured elements
-   `mask_all_element_attributes`: Specifies if PostHog should capture the attributes of autocaptured elements
-   `session_recording`: Accepts an object that lets you configure the following `rrweb` options:
    -   `blockClass`
    -   `blockSelector`
    -   `ignoreClass`
    -   `maskAllInputs`
    -   `maskInputOptions`
    -   `maskInputFn`
    -   `slimDOMOptions`
    -   `collectFonts`

See our [JS Integration page](https://posthog.com/docs/integrations/js-integration) for more details.

-   [Track session starts](https://posthog.com/plugins/first-time-event-tracker)

Our First Time Event Tracker plugin now also tracks session starts. By enabling it you will get `session_started` events in PostHog, as well as events that started a session will be tagged with property `is_first_event_in_session` set to `true`.

### 1.23.1 - Monday 22 March 2021

-   [Optimized Background Action Calculation](https://github.com/PostHog/posthog/pull/3717).

We've made the interval between background action calculations configurable, with a default of 5 minutes. Previously the interval was set in stone at 30 seconds, which could cause unmanageable database load in some conditions.

### 1.23.0 - Thursday 18 March 2021

-   [Date Filter for Heatmaps](https://github.com/PostHog/posthog/pull/3586)

![Toolbar Date Filter](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/toolbar-date.png)

Following a fierce battle with Webpack, Marius brought us the heatmap date filters.

Our heatmaps are now on a whole new level as they are no longer set to show only the last 7 days but allow you to pick any date range. You can now see heatmaps of yesterday, the last 30 days, or any range you like!

-   [Automatic Filtering of Test Accounts](https://github.com/PostHog/posthog/pull/3492)

![Filter test accounts](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/filter-test-accounts.png)

If you've ever found yourself looking at a graph and wondering: "how much do events from me and my team affect this data?", well, your days of wondering are over.

We now provide you with a toggle in 'Insights' to automatically filter out test accounts and your team's accounts your team from your graphs. Out of the box we provide you with some basic relevant filters, but you can also configure this yourself in 'Settings'.

-   [Webhooks Are Back - And They're Better](https://github.com/PostHog/posthog/pulls?q=is%3Apr+is%3Aclosed+webhook)

![Webhooks](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/webhooks.png)

Members of our community pointed out to us that our latest release caused some issues with webhooks on self-hosted FOSS installations. Largely with help from various community members who provided us with context and feedback, we have now addressed these issues and webhooks should work as normal on 1.23.0.

However, we made sure to throw in a little treat to make up for it. You can now access all event properties in your webhook messages, which opens up a whole new realm of possibilities for creating useful alerts and notifications for when certain actions are triggered in PostHog.

-   [Organization Settings & Gravatar Support](https://github.com/PostHog/posthog/pull/3584)

![Gravatars](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/gravatar.png)

PostHog now has an 'Organization Settings' page that lets you rename and delete your organization, as well as manage invites.

Oh, and don't we all love gravatars?

Well, if you have one set for your email, PostHog will now display it on your profile and the 'Organization Settings' page.

-   [First Time Event Tracker Plugin](https://posthog.com/plugins/first-time-event-tracker)

![](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/first-time-plugin.png)

Based on user requests, we have now built a plugin that adds two boolean properties to your events:

-   `is_event_first_ever`: tells you if the event if the first event of its kind
-   `is_event_first_for_user`: tells you if the event is the first event of its kind for the user

By enabling it you are then able to add a filter for those properties on all your analytics, to determine things like conversion rates from first touch.

> **Important:** This plugin will only work on events ingested after the plugin was enabled. This means it will register events as being the first if there were events that occurred before it was enabled.

### 1.22.0 - Wednesday 3 March 2021

#### Important Announcement for Self-Hosted Users

If you're self hosting PostHog, make sure you have your plugin server up and running correctly. You can check that this is the case by looking at the color of the middle circle on the top left of the PostHog UI.

If your plugin server is running, this will be a green checkmark, and hovering over it will give the message "All systems operational", like so:

![Plugin server](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/plugin-server.png)

From this version (1.22.0) onwards, if your plugin server is not running, this circle will turn orange/yellow. You can click on the server to verify if your plugin server is indeed the problem.

This is important because from the next release onwards we will move our event ingestion to the plugin server, meaning that you **will not be able to ingest events** if your plugin server isn't running.

-   [Bar Charts by Graph Series/Value](https://github.com/PostHog/posthog/pull/3457)

![Bar chart by values](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/bar-value.png)

Before this change, our bar charts would always be time-based, meaning that if you had multiple graph series (values), these would just all be stacked into one bar for each time period.

However, we now support two different types of bar charts! When selecting a chart type, you will see the options 'Time' and 'Value' under 'Bar Chart'. Selecting 'Value' will give you the view from the image above, where each graph series is represented in a separate bar, with the value consisting of the aggregate value for the time period specified.

-   [UTM Tags Automatically Set as User Properties](https://github.com/PostHog/plugin-server/pull/214)

![UTM Tags](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/utm-tags.png)

PostHot now automatically sets user properties from [UTM tags](https://en.wikipedia.org/wiki/UTM_parameters). You can now filter and create cohorts of users much more easily based on what campaign, source, or medium brought them to your product or landing page. This is a big feature for us as it gives our users an automatic way of connecting marketing and product to have a more complete view of your business. We're very excited for our community to start using this feature and extending it through [plugins](https://posthog.com/docs/plugins/).

-   [Multiple Value Selector for Equality Filters](https://github.com/PostHog/posthog/pull/3422)

![Multiple equality selector](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/multiple-selector.png)

Writing complex filters is now easier than ever before. You can now select multiple values for Equality Filters instead of just one - this will simplify filter creation and debugging and just save people a lot of time!

-   [Refreshing Dashboards and Updating Time Range for All Panels](https://github.com/PostHog/posthog/pull/3363)

![Dashboards New UX](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/dashboards-ux.png)

It's now easier to work through your key metrics in Dashboards:

-   All dashboard panels can be refreshed at the same time to ensure you're not seeing cached results
-   Time ranges for all dashboard panels can be changed at the same time
-   The dashboard author and creation time are displayed below the title

-   [A Much Better UI for Person Pages](https://github.com/PostHog/posthog/pull/3461)

![Persons New UX](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/persons-v2.png)

The UI of our person pages just got a whole lot better! As is often the case with our larger features, this isn't news to all of you. We had this behind a feature flag and have now decided to roll it out for everyone.

Now you can visualize user properties alongside a user's events, and most of the context you need on a person is available to you in a sleek UI without you needing to scroll.

Oh, and the code got much better as a result too...

-   [Exposing $set and $set_once on all events](https://github.com/PostHog/posthog/pull/3363)

![Set properties on any event](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/%24set.png)

The event properties `$set` and `$set_once` can now be used on any event to set properties directly to the user associated with that event.

Previously, this would only work on `$identify` events, making it so that you needed to call multiple methods in order to send an event and set user properties based on the same data. But now, you can do it all in one, as shown in the image above.

-   [Event Sequence Timer Plugin](https://posthog.com/plugins/event-sequence-timer-plugin)

![Event Sequence Timer Plugin](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/time-events.png)

Our users requested a way to measure the time passed between certain events, and this is it!

By installing the Event Sequence Timer Plugin, you can specify as many sets of events as you want and the plugin will track the time between them, either using a first touch or last touch mechanism.

It will then add a property to your events that allows you to easily build visualizations in PostHog of the average, minimum, and maximum time between events, as well as all the other mathematical operations we support.

-   [Property Flattener Plugin](https://posthog.com/plugins/property-flattener)

![Property Flattener Plugin](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/flattener.png)

The new Property Flattener Plugin allows you to convert event properties contained in a nested structure into a flat structure, allowing you to set filters based on the nested properties.

-   [Project API Key Autofill in Docs for Cloud Users](https://github.com/PostHog/posthog.com/pull/998)

![Docs Token Autofill](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/token-autofill.png)

If you're a user of PostHog Cloud, we now autofill your Project API Key and API Host automatically in the Docs for you, meaning you can copy-paste snippets and use them directly with no manual changes!

This key will be based on the last project you used in PostHog, and you can check what project that is by simply hovering your cursor over the highlighted key.

### 1.21.0 - Wednesday 17 February 2021

-   [New Navigation For All](https://github.com/PostHog/posthog/pull/3167)

![New Nav](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/new-navigation.png)

While this might not be news to all of you, we have now released our new navigation to everyone.

We had this behind a feature flag, but now all our users have access to our fresh spaceship-like navigation. What do you think? 🚀

-   [Refreshing Insights](https://github.com/PostHog/posthog/pull/3144)

![Refreshing Insights](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/refreshing-insights.png)

To provide a smooth user experience, we cache query results so that you don't have to wait for a query to run every time you go back to a chart you've recently looked at.

However, this might mean you're sometimes looking at slightly outdated results. As such, we now clearly indicate to you if you're looking at a cached result, how long ago this result was computed, and allow you to refresh it any time you want to see an updated result.

-   [Session Recording Filters](https://github.com/PostHog/posthog/pull/2993)

![Session filters](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/session-filters.png)

Our session recording filters just got **so much more powerful**.

Filter by session duration, user properties, unseen recordings, actions performed in a session, and so much more.

You can now get a lot more out of your session recording sessions by tailoring the recordings to specific areas of your product you're looking into.

For a start, how about [integrating PostHog with Sentry](https://posthog.com/docs/integrations/sentry-integration) and watching all recordings with an `$exception` event in them?

-   [Multiple Groups in Feature Flags](https://github.com/PostHog/posthog/pull/3030)

![Feature Flag Multiple Groups](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/feature-flag-groups.png)

Feature flags can now be rolled out to multiple different groups that use distinct settings, unlocking a whole new world of opportunities for your A/B testing and feature rollout processes.

For example, you can now determine a feature flag to be rolled out to all of the following:

-   100% of users in the 'Beta Testers' cohort
-   40% of all your users
-   All users in a specific team that requested the feature from you

You can then adjust the filters and rollout percentage for each individually, giving you an even greater degree of flexibility with how you leverage our flags in your workflows.

-   [A New Plugins UI with Brand New Features](https://github.com/PostHog/posthog/pull/2774)

![Plugins UI](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/plugins-ui.png)

A lot has happened to our plugins feature since the last release, including:

-   An improved UI
-   The ability to reorder plugins
-   The ability to upgrade plugins (and see exactly what changed between plugin versions)
-   Autofill on commonly used plugin configuration fields
-   A new plugin configuration field type, letting plugin builders specify pre-determined choices for the user to select from
-   A ton of performance improvements

*   [Taxonomy Plugin](https://posthog.com/plugins/taxonomy-standardizer)

![Taxonomy Plugin](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/taxonomy-plugin.png)

Standardize your event names into a single naming pattern by converting the names of your events that don't match your desired pattern into the chosen format, such as `camelCase` or `snake_case`.

-   [Bitbucket Release Tracker Plugin (Beta)](https://posthog.com/plugins/bitbucket-release-tracker)

![Bitbucket Plugin](https://github.com/PostHog/bitbucket-release-tracker/raw/main/readme-assets/release-tracker.png)

Get your Bitbucket release tags into PostHog as annotations on your graphs, so you can track the impact of releases on your metrics.

### 1.20.0 - Tuesday 19 January 2021

-   [Plugins, Plugins, and more Plugins](https://posthog.com/plugins)

![Plugin Library Screenshot](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/plugin-library.png)

A lot has been happening on our Plugins front.

Besides a whole bunch work to deliver performance improvements and mature the PostHog Plugins ecosystem, we have two major changes being introduced with this new PostHog version:

**A shiny new plugin library**

We have released a [plugin library](https://posthog.com/plugins) where you can browse through all the plugins built by our core team and community, and made sure the library is populated with plugins! Thus, we now have integrations that support getting data from GitHub and GitLab, or sending data over to BigQuery and Hubspot, for example.

We're working to make plugins available on Cloud, but, in the meanwhile, if you're self-hosting, do check out our plugins and let us know what you think!

**Plugins can now access persistent storage**

Up until now, plugin builders would have noticed that the `cache` could have been used to store data in-memory using Redis, but we now also support `storage`, which allows plugins to store data in a persistent form, opening up a lot of new use cases for you to explore.

-   [Static Cohorts](https://github.com/PostHog/posthog/pull/2932)

![Static Cohorts Screenshot](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/static-cohorts.png)

In addition to our standard dynamic cohorts (periodically updated based on the definition), PostHog now support static cohorts - groups of users that don't update.

To create a static cohort, head over to 'People' -> 'Cohorts' and, when creating a new cohort, select 'Upload CSV'. This CSV file should have a single column with either the user's `distinct_id` or `email`.

This way, you can import data from outside sources into a PostHog cohort more easily, as well as turn your dynamic cohorts into static ones by first exporting them. You could, for example, add your Mailchimp subscribers list as a static cohort.

-   [Sortable Funnel Steps](https://github.com/PostHog/posthog/pull/2862)

![Sortable Funnels Screenshot](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/funnel-step-reordering.png)

As of this new release, when you head over to Funnels in PostHog, you will see 3 dots next to each funnel step. By dragging these 3 dots up and down you can now re-order your funnel's steps, for example if you made a mistake, or want to explore different funnel structures.

This was a feature that was consistently requested by the PostHog community, and we'd like to also shoutout [@glmaljkovich](https://github.com/glmaljkovich) for helping us build it!

-   [PostHog Bookmarklet](https://github.com/PostHog/posthog/pull/2774)

![Bookmarklet Gif](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Array/bookmarklet.gif)

To try out the PostHog snippet without having to update anything on your codebase, you can make use of our bookmarklet, which you can find over in 'Project Settings'.

This lets you capture events in your website without any code, and we've been using it actively during our demos!

-   [Sessions List now loads 10x faster](https://github.com/PostHog/posthog/pull/2934)

Since joining us, Karl has been submitting performance improvement after performance improvement.

This time, as session recordings are being used more and more by our users, it was time to speed up the loading of the sessions list, which now loads 10x faster!

### 1.19.0 - Tuesday 15 December 2020

-   [Scheduled Plugins and Editor](https://github.com/PostHog/posthog/pull/2743)

![Plugin Editor Screenshot](https://posthog.com/static/f4aae550d6d85f934877d6e2c9e787c8/8c557/plugin-editor.png)

We now support scheduled plugins that run periodically on a specified time cycle (e.g. minute, hour, day), as well as have a built-in code editor for plugins right into the PostHog UI.

With the ability to run tasks in specified time intervals, you can now setup plugins that, for example, keep track of external metrics and add this data to PostHog via new events. This is possible because we now [support `posthog.capture` calls inside plugins as well](https://github.com/PostHog/posthog-plugin-server/pull/67).

Some metrics you might want to keep track of are, for example, server performance, GitHub activities (e.g. stars ⭐ ), engagement with your project's social media profiles, and anything else you can think of!

You can learn more about scheduled plugins on the [PR that created them](https://github.com/PostHog/posthog-plugin-server/pull/63), as well as our docs for [building your own plugin](https://posthog.com/docs/plugins/build).

> **Note:** Plugins are a Beta feature currently only available on self-hosted instances. We are working to make it available on PostHog Cloud soon.

-   [Lifecycle Analysis](https://github.com/PostHog/posthog/pull/2460)

![Lifecycle Screenshot](https://posthog.com/static/b577dd0e4d2817e816ba602e5ef94e1d/8c557/lifecycle.png)

Our 'Trends' tab just got an awesome new feature: lifecycle graphs!

Lifecycle analysis digs deeper into your events and shows you a breakdown of the users who performed the event into new, returning, and resurrecting users. In addition, it also shows you the churn on for the specified time period.

To use it, select 'Shown As' -> 'Lifecycle' when in the 'Trends' tab.

-   [New Session Recording Compression Scheme](https://github.com/PostHog/posthog/pull/2578)

![Gzip Session Recording Screenshot](https://posthog.com/static/fe91676a24a8c70a017fafe2ab68f63e/8c557/session-recording-gzip.png)

See the image above? That's our event processing time before and after the new compression scheme!

By using gzip-based compression, we have now significantly improved performance both on the client and server, making event processing faster, as well as decreasing the number of session recordings that are lost. Be on the lookout for more green play buttons on your 'Sessions' page now.

> If you installed `posthog-js` via `npm`, you should update to version 1.8.0 to get access to this update. Snippet users have access to the latest version by default.

-   [New Actions UX](https://github.com/PostHog/posthog/pull/2615)

![New Actions UX Screenshot](https://posthog.com/static/1f931cd359d1238e8ecba8d72a0be0c4/8c557/actions-ux.png)

This might not be news to all of you, since we have been experimenting with our actions UX using [feature flags](https://posthog.com/docs/features/feature-flags). However, we're now rolling out a new UX for creating actions to all PostHog users, so try it out let us know what you think!

-   [New operations for numerical properties](https://github.com/PostHog/posthog/pull/2630)

In addition to the average, sum, maximum, and minimum operations available to numerical properties in trends, we now also support median, and 90th, 95th, and 99th percentiles.

#### [Full Release Notes](https://posthog.com/blog/the-posthog-array-1-19-0)

### 1.18.0 - Monday 30 November 2020

Our primary goals for this release were to iron out bugs and improve the user experience of our Beta features.

As a result, we fixed **a whole lot of stuff**. We merged dozens of PRs with session recording fixes and improvements, and a dozen more with updates to our plugins functionality. We also improved things like event ingestion, the UX for feature flags, and our settings for both organizations and projects. You can read through the entire list of fixes [on our website](https://posthog.com/blog/the-posthog-array-1-18-0#bug-fixes-and-performance-improvements), but beware: it's quite long.

-   [New Event Selection Box](https://github.com/PostHog/posthog/pull/2394)

![Events Box Screenshot](https://posthog.com/static/f0cb8a60445756b897447700d38f0ed5/2cefc/events-box.png)

We upgraded our event selection box to include actions and events in one, as well as provide smarter recommendations of events and actions you might want to use of based frequently used in queries by you or your team.

-   [Improvements to posthog-js](https://github.com/PostHog/posthog-js)

A new version of `posthog-js` is available and we recommend you to update if you've installed it via `npm`. Snippet users have access to the latest version by default.

The new version includes a lot of bugfixes that improve our session recording feature, as well as is significantly lighter, having had [a lot of legacy code removed](https://github.com/PostHog/posthog-js/pull/128).

R.I.P. to the hundreds of lines of JavaScript that were removed - you will not be missed.

-   [Plugins are now available on Kubernetes deployments](https://github.com/PostHog/charts/pull/24)

Following feedback from a user, we have now added support for [PostHog Plugins](https://posthog.com/docs/plugins/overview) to our Helm chart.

If you're using the chart to deploy PostHog, upgrading to the latest version will give you access to the new plugin server (Beta).

-   [Session Recording Improvements](https://github.com/PostHog/posthog/pulls?q=is%3Apr+is%3Aclosed+session)

Out of the many improvements to session recording, there are some worth mentioning specifically:

-   Keyboard shortcuts for the session recording player (`spacebar` to pause/play, `f` to open player in full screen)
-   Ability to jump back/forward 8 seconds with the keyboard arrows (or player button)
-   Full-screen support for the session recording player without losing the controls bar
-   Pause/Play recording when clicking on the video
-   Skipping inactivity made clearer with an overlay over the player
-   The session recording player is now responsive to the client's screen size
-   Incomplete session recordings (i.e. "blank screens") are now hidden from the list

### 1.17.0 - Tuesday 17 November 2020

-   [Sentry Integration](https://github.com/PostHog/posthog/pull/1833)

![Sentry Screenshot](https://posthog.com/static/85a8c81d33e2e3647657b389c0b12814/2cefc/sentry.png)

An important part of developing a great user experience is identifying, tracking, and fixing bugs.

With our new [Sentry](https://sentry.io/) integration, you can (i) leverage PostHog data to help your debugging (ie to see the user's event history or to watch a session recording), and (ii) use Sentry exception data to quickly spot if errors are affecting your product metrics (ie to see if errors are causing churned users).

As a two-way integration, it:

-   Adds a direct link in Sentry to the profile of the person affected in PostHog
-   Sends an `$exception` event to PostHog with a direct link to Sentry

If you're unfamiliar with Sentry, we highly recommend you to check it out - it is an awesome application monitoring platform of which we're avid users at PostHog.

To set up the integration you can read the step-by-step instructions on the dedicated [Sentry Integration page](https://posthog.com/docs/integrations/sentry-integration).

-   [RudderStack Integration](https://docs.rudderstack.com/destinations/posthog)

RudderStack is an open-source, warehouse-first, customer data platform for developers. It allows you to collect and deliver customer event data to a variety of destinations such as data warehouses and analytics platforms.

As of last week, PostHog is now available as a destination on RudderStack, allowing you to send your event data from various sources into PostHog for performing product analytics.

You can read more about RudderStack on [their website](https://rudderstack.com/), and learn how to integrate PostHog through their [comprehensive integration docs](https://docs.rudderstack.com/destinations/posthog).

-   [Plugin Attachments and GeoIP Plugin](https://github.com/PostHog/posthog/pull/2263)

![MaxMind Plugin Page Screenshot](https://posthog.com/static/db00f5bcf26ff68ad3e8fe14cde54dcb/2cefc/maxmind-plugin.png)

Over the past two weeks, our [Plugins](https://posthog.com/docs/plugins/overview) feature was extensively worked on to improve the experience of using and developing plugins for PostHog.

One of the main changes was the addition of plugin attachments, which allow you to upload files that are used in the configuration of the plugin, vastly expanding the realm of possibilities of what plugins can do.

As a result of this, we built the [PostHog MaxMind Plugin](https://posthog.com/docs/plugins/maxmind), leveraging attachments to allow GeoIP data to be used for enriching your events. Once configured, the plugin adds IP-based location information as properties on your events, such as what country and city your users are located in, making it possible to create charts and tables filtered based on the location of your users.

> **Note:** Plugins are currently only available on self-hosted instances. If you're self-hosting and want to use the PostHog MaxMind Plugin, please follow [these instructions](https://posthog.com/docs/plugins/maxmind). If you want to build your own plugin, check out our [fresh new guide](https://posthog.com/docs/plugins/build) on how to do so.

-   [Retentions & Paths Dashboard Panels](https://github.com/PostHog/posthog/pull/2201)

![Retention Panel Screenshot](https://posthog.com/static/adc21b7a7d974cc268481fd4d55b2c29/2cefc/retention-panel.png)

Dashboards are a key part of PostHog, so it's important to us that you can have an overview of as many as possible of your metrics in them.

As such, the user paths graph and the retention table can now be added as panels on dashboards, making it so that every single chart, table, funnel, and graph you create in PostHog can make it to your dashboards now.

-   [First Time Retention](https://github.com/PostHog/posthog/pull/2325)

![First Time Retention Screenshot](https://posthog.com/static/61a2f75d668da309c8800cfc2b4478c7/2cefc/first-time-retention.png)

Following some feedback from our own Growth Engineer on what functionality we need for ourselves at PostHog, we have now extended the functionality of our 'Retention' view, adding first time retention and differentiating between 'Cohortizing' and 'Retaining' events.

In short, first time retention cohortizes users based on when they did an event for the **first time**, rather than adding a user to each cohort they had the event in. Additionally, by being able to have different target events for the cohort and the retention, you are able to track the impact of 'Event A' on the retention of 'Event B', exploring hypotheses such as how users who read your documentation retain on product pageviews when compared to other users.

-   [New Events & Actions View](https://github.com/PostHog/posthog/pull/2319)

![Manage Events View Screenshot](https://posthog.com/static/73e3d54092192d20c9f686152685a82e/2cefc/manage-events.png)

In an effort to make it easier to filter through your events in PostHog and tag events that you find useful, we have now consolidated 'Events' and 'Actions' into one single view, found on the left sidebar as 'Events & Actions'.

On this page, you'll be able to manage everything related to your events, from inspecting their properties, to tagging them as actions. In addition, we have also added stats for your event and property volumes, so you can dig deeper into your analytics data collection, and optimize it to your needs.

-   [Improved AWS CloudFormation Deployment](https://github.com/PostHog/deployment/pulls?q=is%3Apr+is%3Aclosed)

Following a lot of great user feedback, we have now significantly improved our [AWS CloudFormation Deployment](https://posthog.com/docs/deployment/deploy-aws).

We have now added configuration for relevant alerts and RDS disk size, as well as improved the setup flow and added automatic `SECRET_KEY` generation. If you're happy with the standard config, deploying with AWS is now just a matter of "click, click, click", as described by Karl, one of our engineers.

### 1.16.0 - Wednesday 4 November 2020

-   [Session Recording (Beta)](https://github.com/PostHog/posthog/issues/1846)

![Session Recording Page Screenshot](https://posthog.com/static/dec14fdf98d81deada734c03126d482f/2cefc/session-recording.png)

Given that our mission at PostHog is to increase the number of successful projects in the world, session recording felt like a feature that fits in perfectly with that goal.

PostHog already provides various features to help you understand and improve your UX - but watching real users use your product is a _whole other ball game_.

With PostHog's session recording, you are able to truly feel the pain points of your users first-hand, seeing where they get stuck, debugging exceptions faster, and making your UX smoother.

![Session Recording Screenshot](https://posthog.com/static/677bd4dc1f4ff4c2b0b2509e66f1e7ea/2cefc/session-recording-ss.png)

Additionally, you can do so while still preserving the privacy of your users, by determining what shouldn't be captured, as well as being able to turn session recording on and off as you wish.

However, please note that our session recording feature is in **Beta** at the moment. This means that it can be unstable and have bugs. To report bugs you find while using it, please [open an issue for us on GitHub](https://github.com/PostHog/posthog/issues).

If you have posthog-js [installed via npm](https://www.npmjs.com/package/posthog-js) you will need to update to latest version.

-   [Plugins (Beta)](https://github.com/PostHog/posthog/issues/1896)

![Plugins Screenshot](https://posthog.com/static/f84e34e19a7715f563dabe7c2d3ca823/2cefc/plugins.png)

Plugins is another **Beta** feature that we're extremely excited for. Currently only available for self-hosted instances, plugins allow you to add additional logic to your event processing pipeline, in order to do things like enrich your data or send it somewhere else, for instance to a data warehouse.

At the moment, we have created a few example plugins for you to test out the functionality, and have the intention of launching more for the next release. We will also be launching tutorials on how to make your own plugins, so stay tuned for that.

As of right now, if you're on a self-hosted instance, you should head over to 'Project' -> 'Plugins' to enable the functionality. You can start testing it out with our "Hello World" plugin, which adds a property to your events called `foo` with a value that is up to you to decide in setup.

We also have built plugins for currency normalization and GeoIP data, allowing you to convert currency values in events according to up-to-date exchange rates and determine the location of an event based on the user's IP.

Our overall vision for plugins is to enable seamless integration with other relevant data analytics platforms, as well as allow users to more easily customize PostHog's functionality by adding their own logic and data to the event pipeline.

Finally, as is the case with session recording, please report any bugs in the functionality on [GitHub](https://github.com/PostHog/posthog/issues).

-   [Multiple Projects](https://github.com/PostHog/posthog/pull/1562)

![Multiple Projects Screenshot](https://posthog.com/static/821f1e938621ad7d37e1ce0e9a3704a9/2cefc/org-project.png)

You asked and we delivered!

As per feedback from many in our community, PostHog now offers support for managing multiple projects under one "umbrella" organization.

This allows you to segregate concerns, such as keeping tracking for your dev and prod environments separately, as well as track multiple domains and apps without mixing data.

In addition, we also enhanced our invite and permissioning system as a by-product of this feature.

As this is an Enterprise Edition feature, please contact us at _sales@posthog.com_ if you are interested in using it.

-   [Dashboard Templates](https://github.com/PostHog/posthog/pull/1942)

![Dashboard Templates Screenshot](https://posthog.com/static/1430069845eb4f0a34a7d4afc9b9fa30/2cefc/dashboard-template.png)

In order to make it easier to create valuable dashboards to keep track of your business metrics, PostHog now offers the option to create new dashboards based on a template. We will be expanding the power of dashboard templates, but, as of right now, you can already create a dashboard using our web app dashboard template, which provides you with a good starting point for determining and tracking relevant metrics.

-   [Setup Improvements](https://github.com/PostHog/posthog/pull/1990)

![Google Login Screenshot](https://posthog.com/static/14e1269485fcf90f90e761b1accbeb34/2cefc/google-login.png)

In addition to GitHub and GitLab authentication, PostHog now supports signup and login with Google accounts!

We also improved our setup process by better structuring our settings pages, allowing you to [change your project's token](https://github.com/PostHog/posthog/pull/2015), and [enhancing the UX for empty states on dashboards](https://github.com/PostHog/posthog/pull/2068).

-   [Documentation Level Up](https://github.com/PostHog/posthog.com)

![Docs Screenshot](https://posthog.com/static/5b1046b5a6615c1cd91af2519b8d603d/2cefc/docs.png)

We have been working hard to improve our product documentation and had a few big upgrades recently:

-   Our Docs now have a Dark Mode option
-   You can search our entire documentation without ever using your mouse
-   We are actively releasing new tutorials on how to use PostHog to track key metrics and improve your product
-   Our Docs pages now load faster
-   New screenshots have been added throughout the Docs, as well as functionality walkthrough videos

…and a lot more!

If you have any suggestions for new tutorials or improvements to our documentation, [do not hesitate to let us know!](https://github.com/PostHog/posthog.com/issues)

We’re working hard to improve PostHog and would love to talk to you about your experience with the product.
If you're interested in helping us out, you can schedule a quick 30-min call with us [on Calendly](https://calendly.com/posthog-feedback).

Oh, and we're giving away some awesome [PostHog merch](https://merch.posthog.com) as a thank you!

## Bug Fixes and Performance Improvements

-   Retention UX fixes [\#2168](https://github.com/PostHog/posthog/pull/2168) ([EDsCODE](https://github.com/EDsCODE))
-   Simplify action queries [\#2167](https://github.com/PostHog/posthog/pull/2167) ([timgl](https://github.com/timgl))
-   Prune person materialized [\#2166](https://github.com/PostHog/posthog/pull/2166) ([EDsCODE](https://github.com/EDsCODE))
-   Switch to the official Heroku Python buildpack [\#2151](https://github.com/PostHog/posthog/pull/2151) ([edmorley](https://github.com/edmorley))
-   Slim down dev docker image [\#2147](https://github.com/PostHog/posthog/pull/2147) ([timgl](https://github.com/timgl))
-   Clickhouse binary capture [\#2146](https://github.com/PostHog/posthog/pull/2146) ([timgl](https://github.com/timgl))
-   Fix funnel loading and other UX issues [\#2134](https://github.com/PostHog/posthog/pull/2134) ([timgl](https://github.com/timgl))
-   Fix elements chain with bad classes [\#2133](https://github.com/PostHog/posthog/pull/2133) ([timgl](https://github.com/timgl))
-   Fix social auth account creation [\#2123](https://github.com/PostHog/posthog/pull/2123) ([Twixes](https://github.com/Twixes))
-   Flatten array and check length for actions [\#2120](https://github.com/PostHog/posthog/pull/2120) ([EDsCODE](https://github.com/EDsCODE))
-   \[Clickhouse\] speed up sessions list [\#2118](https://github.com/PostHog/posthog/pull/2118) ([timgl](https://github.com/timgl))
-   Fix for action/event dropdown [\#2117](https://github.com/PostHog/posthog/pull/2117) ([EDsCODE](https://github.com/EDsCODE))
-   Make DELETE synchronous in clickhouse tests / make tests less flaky [\#2116](https://github.com/PostHog/posthog/pull/2116) ([macobo](https://github.com/macobo))
-   Capture social_create_user exception with Sentry [\#2115](https://github.com/PostHog/posthog/pull/2115) ([Twixes](https://github.com/Twixes))
-   Clarify invite creation [\#2113](https://github.com/PostHog/posthog/pull/2113) ([Twixes](https://github.com/Twixes))
-   \[Clickhouse\] More speed optimizations for funnels [\#2109](https://github.com/PostHog/posthog/pull/2109) ([timgl](https://github.com/timgl))
-   Fix changelog images [\#2105](https://github.com/PostHog/posthog/pull/2105) ([yakkomajuri](https://github.com/yakkomajuri))
-   Debug redis leak [\#2102](https://github.com/PostHog/posthog/pull/2102) ([mariusandra](https://github.com/mariusandra))
-   Clickhouse improve funnel speed [\#2100](https://github.com/PostHog/posthog/pull/2100) ([timgl](https://github.com/timgl))
-   Reduce Heroku worker thread count [\#2092](https://github.com/PostHog/posthog/pull/2092) ([mariusandra](https://github.com/mariusandra))
-   Wire up the length to the proto message [\#2089](https://github.com/PostHog/posthog/pull/2089) ([fuziontech](https://github.com/fuziontech))
-   Start with a new topic [\#2088](https://github.com/PostHog/posthog/pull/2088) ([fuziontech](https://github.com/fuziontech))
-   Provide required proto message length for our clickhouse overlords [\#2087](https://github.com/PostHog/posthog/pull/2087) ([fuziontech](https://github.com/fuziontech))
-   Clickhouse window funnel [\#2086](https://github.com/PostHog/posthog/pull/2086) ([timgl](https://github.com/timgl))
-   Protobufize events to protect from malformed JSON [\#2085](https://github.com/PostHog/posthog/pull/2085) ([fuziontech](https://github.com/fuziontech))
-   \#2083 Ignore result [\#2084](https://github.com/PostHog/posthog/pull/2084) ([timgl](https://github.com/timgl))
-   Add CH Person Sessions By Day [\#2082](https://github.com/PostHog/posthog/pull/2082) ([yakkomajuri](https://github.com/yakkomajuri))
-   Fix bin/tests too many files watching error [\#2078](https://github.com/PostHog/posthog/pull/2078) ([timgl](https://github.com/timgl))
-   Fix retention label and add tests [\#2076](https://github.com/PostHog/posthog/pull/2076) ([EDsCODE](https://github.com/EDsCODE))
-   Make possible CI optimizations [\#2074](https://github.com/PostHog/posthog/pull/2074) ([Twixes](https://github.com/Twixes))
-   Attempt to speed up 3.9 tests [\#2073](https://github.com/PostHog/posthog/pull/2073) ([macobo](https://github.com/macobo))
-   Fix cypress tests [\#2070](https://github.com/PostHog/posthog/pull/2070) ([macobo](https://github.com/macobo))
-   Give staff users superuser permissions [\#2069](https://github.com/PostHog/posthog/pull/2069) ([Twixes](https://github.com/Twixes))
-   Fix loading people and stickiness [\#2067](https://github.com/PostHog/posthog/pull/2067) ([EDsCODE](https://github.com/EDsCODE))
-   Improved settings for session recording [\#2066](https://github.com/PostHog/posthog/pull/2066) ([macobo](https://github.com/macobo))
-   Fix History button layout in Insights [\#2065](https://github.com/PostHog/posthog/pull/2065) ([Twixes](https://github.com/Twixes))
-   Fixes bad timerange for retentino [\#2064](https://github.com/PostHog/posthog/pull/2064) ([EDsCODE](https://github.com/EDsCODE))
-   Autoimport celery tasks [\#2062](https://github.com/PostHog/posthog/pull/2062) ([macobo](https://github.com/macobo))
-   Limit ingestion for teams [\#2060](https://github.com/PostHog/posthog/pull/2060) ([fuziontech](https://github.com/fuziontech))
-   Clickhouse never calculate action [\#2059](https://github.com/PostHog/posthog/pull/2059) ([timgl](https://github.com/timgl))
-   Bump cryptography from 2.9 to 3.2 [\#2058](https://github.com/PostHog/posthog/pull/2058) ([dependabot[bot]](https://github.com/apps/dependabot))
-   Clickhouse move to JSON extract for all filters [\#2056](https://github.com/PostHog/posthog/pull/2056) ([timgl](https://github.com/timgl))
-   Fix cohorts clickhouse [\#2052](https://github.com/PostHog/posthog/pull/2052) ([timgl](https://github.com/timgl))
-   Fix flaky test [\#2048](https://github.com/PostHog/posthog/pull/2048) ([EDsCODE](https://github.com/EDsCODE))
-   Upgrade kea-router and typegen [\#2044](https://github.com/PostHog/posthog/pull/2044) ([mariusandra](https://github.com/mariusandra))
-   Use jsonextract for steps in funnel query [\#2040](https://github.com/PostHog/posthog/pull/2040) ([EDsCODE](https://github.com/EDsCODE))
-   Use uuids in funnels for consistency [\#2036](https://github.com/PostHog/posthog/pull/2036) ([timgl](https://github.com/timgl))
-   \[Clickhouse\] fix events for action with no steps [\#2035](https://github.com/PostHog/posthog/pull/2035) ([timgl](https://github.com/timgl))
-   Fix funnels with multiple property filters [\#2034](https://github.com/PostHog/posthog/pull/2034) ([timgl](https://github.com/timgl))
-   Restore original retention query [\#2029](https://github.com/PostHog/posthog/pull/2029) ([EDsCODE](https://github.com/EDsCODE))
-   Filter person_distinct_id table further before joining [\#2028](https://github.com/PostHog/posthog/pull/2028) ([EDsCODE](https://github.com/EDsCODE))
-   Fix typescript errors \#1 [\#2027](https://github.com/PostHog/posthog/pull/2027) ([mariusandra](https://github.com/mariusandra))
-   Remove useless User.is_superuser [\#2026](https://github.com/PostHog/posthog/pull/2026) ([Twixes](https://github.com/Twixes))
-   Get rid of Py 3.7-incompatible typing.Literal [\#2025](https://github.com/PostHog/posthog/pull/2025) ([Twixes](https://github.com/Twixes))
-   Update person property filtering [\#2024](https://github.com/PostHog/posthog/pull/2024) ([EDsCODE](https://github.com/EDsCODE))
-   Add eslint rule for empty JSX elements [\#2023](https://github.com/PostHog/posthog/pull/2023) ([mariusandra](https://github.com/mariusandra))
-   Fix click outside spam & public paths [\#2022](https://github.com/PostHog/posthog/pull/2022) ([mariusandra](https://github.com/mariusandra))
-   \[Clickhouse\] Fix action filtering on events [\#2013](https://github.com/PostHog/posthog/pull/2013) ([timgl](https://github.com/timgl))
-   Add types to window.posthog [\#2012](https://github.com/PostHog/posthog/pull/2012) ([macobo](https://github.com/macobo))
-   Rename existing projects to "Default Project" [\#2009](https://github.com/PostHog/posthog/pull/2009) ([Twixes](https://github.com/Twixes))
-   Enable compatibility with old Team signup links [\#2007](https://github.com/PostHog/posthog/pull/2007) ([Twixes](https://github.com/Twixes))
-   Add tests to important query builders [\#2006](https://github.com/PostHog/posthog/pull/2006) ([EDsCODE](https://github.com/EDsCODE))
-   Put organization switcher under user [\#2005](https://github.com/PostHog/posthog/pull/2005) ([Twixes](https://github.com/Twixes))
-   Fix links [\#2004](https://github.com/PostHog/posthog/pull/2004) ([Twixes](https://github.com/Twixes))
-   Cohorts Test [\#2003](https://github.com/PostHog/posthog/pull/2003) ([mariusandra](https://github.com/mariusandra))
-   Patch broken link from changed path [\#2002](https://github.com/PostHog/posthog/pull/2002) ([EDsCODE](https://github.com/EDsCODE))
-   Fix cohort page link [\#2000](https://github.com/PostHog/posthog/pull/2000) ([mariusandra](https://github.com/mariusandra))
-   Break down feature_flag_response and add to propertykeyinfo [\#1991](https://github.com/PostHog/posthog/pull/1991) ([timgl](https://github.com/timgl))
-   Make PostHog compatibile with Python 3.9 [\#1987](https://github.com/PostHog/posthog/pull/1987) ([Twixes](https://github.com/Twixes))
-   Use posthog.js correctly in userLogic [\#1975](https://github.com/PostHog/posthog/pull/1975) ([macobo](https://github.com/macobo))
-   \[Clickhouse\] Fix grabbing by person [\#1960](https://github.com/PostHog/posthog/pull/1960) ([timgl](https://github.com/timgl))
-   Add new person materialized [\#1944](https://github.com/PostHog/posthog/pull/1944) ([EDsCODE](https://github.com/EDsCODE))

### 1.15.1 - Thursday 22 October 2020

-   Fixed issue where 100s of emails would be sent. (oops!)
-   Fixed performance issues with Redis caches filling up.

### 1.15.0 - Thursday 15 October 2020

-   [ClickHouse 👆🏠](https://github.com/PostHog/posthog/pulls?page=1&q=is%3Apr+clickhouse+is%3Aclosed)

![Clickhouse Screenshot](https://posthog.com/static/bf2c9d775b519ae2132048751c1909b0/2cefc/clickhouse.png)

If you've followed our progress on GitHub over the past months, you'll know that ClickHouse has been the talk of the town.

In their own words, ClickHouse is "a column-oriented database management system (DBMS) for online analytical processing of queries (OLAP)".

Or, in simple terms: it's a **very fast database**.

As you may know, we have been using the well-established and reliable PostgreSQL until now, but from here on out our Enterprise Edition will be using ClickHouse instead. PostgreSQL remains a great option for lower volumes, but, for companies that handle huge event volumes, ClickHouse is a much better choice.

On our cloud version we handle event numbers in the nine figures, and implementing ClickHouse has drastically reduced the execution time for all of our queries.

If you're interested in using PostHog with ClickHouse, send us an email at _sales@posthog.com_.

-   [Command Palette](https://github.com/PostHog/posthog/pull/1819)

![Command Palette Screenshot](https://posthog.com/static/8e2f200d5ba2252b33f4bdb20784d614/2cefc/command-palette.png)

<br />

We're super excited about this.

Last week we did an internal hackathon and the command palette was one of the awesome projects to come out of it.

Now, when using PostHog, you can press `⌘K` (Mac) or `Ctrl + K` (Windows) to reveal a Spotlight or Superhuman-like command palette that lets you navigate around PostHog mouse-less. In addition to navigation, the command palette also has page-specific commands that let you, for example, change the time range on charts, as well as a way to quickly share feedback with the PostHog team, create an API key, or even do some math with the built-in calculator.

Eric, Michael, and Paolo got this done in just a few days, and we love it.

Stay tuned for more exciting features that were built during the hackathon.

-   [Backend Feature Flags](https://github.com/PostHog/posthog-python/pull/9)

![Backend Feature Flags Code](https://posthog.com/static/5dfed95825588d03f88309c661539326/2cefc/backend-flags.png)

Based on community feedback, we made it easier for feature flags to be integrated with your backend, in addition to our frontend JavaScript implementation.

We've added feature flag support to our [Python Integration](https://github.com/PostHog/posthog-python/pull/9), as well as [improved the `/decide` endpoint](https://github.com/PostHog/posthog/pull/1592) used by feature flags to make the API experience better.

We have ourselves been using feature flags with the Python integration to slowly roll out some exciting new features.

-   [Weekly Report Email](https://github.com/PostHog/posthog/pull/1700)

![Weekly Email Screenshot](https://posthog.com/static/b2f8999a674c1be5307cafd5bc760070/2cefc/weekly-email.png)

To help users keep up with their key metrics in a simple way, we have introduced a weekly email that gives you an overview of your active and churned users over the previous week.

This is in Beta mode and we're expanding its capabilities, but it already gives you a good sense of your performance in terms of users.

Have you gotten your weekly report yet?

-   [User Interviews](calendly.com/posthog-feedback)

We’re working hard to improve PostHog and would love to talk to you about your experience with the product.

If you're interested in helping us out, you can schedule a quick 30-min call with us [on Calendly](https://calendly.com/posthog-feedback).

Oh, and we're giving away some awesome [PostHog merch](https://merch.posthog.com) as a thank you!

## Bug Fixes and Performance Improvements

-   Add overflow to card body [\#1878](https://github.com/PostHog/posthog/pull/1878) ([EDsCODE](https://github.com/EDsCODE))
-   Pinning the dev Dockerfile PostgreSQL and Redis to the production version [\#1877](https://github.com/PostHog/posthog/pull/1877) ([ahtik](https://github.com/ahtik))
-   Fix path loading spinner [\#1876](https://github.com/PostHog/posthog/pull/1876) ([EDsCODE](https://github.com/EDsCODE))
-   Fix session label hover erroring [\#1874](https://github.com/PostHog/posthog/pull/1874) ([EDsCODE](https://github.com/EDsCODE))
-   Add check to event serializer [\#1873](https://github.com/PostHog/posthog/pull/1873) ([EDsCODE](https://github.com/EDsCODE))
-   Upgrade cypress, fix and stabilize tests [\#1872](https://github.com/PostHog/posthog/pull/1872) ([macobo](https://github.com/macobo))
-   Fix small util bugs [\#1871](https://github.com/PostHog/posthog/pull/1871) ([Twixes](https://github.com/Twixes))
-   Mark js_posthog_host as safe [\#1868](https://github.com/PostHog/posthog/pull/1868) ([macobo](https://github.com/macobo))
-   Destroy lodash [\#1864](https://github.com/PostHog/posthog/pull/1864) ([Twixes](https://github.com/Twixes))
-   Use official react-grid-layout [\#1862](https://github.com/PostHog/posthog/pull/1862) ([Twixes](https://github.com/Twixes))
-   Fix feature flags test [\#1858](https://github.com/PostHog/posthog/pull/1858) ([yakkomajuri](https://github.com/yakkomajuri))
-   Remove redis warning [\#1856](https://github.com/PostHog/posthog/pull/1856) ([timgl](https://github.com/timgl))
-   Trim quotes on event properties [\#1852](https://github.com/PostHog/posthog/pull/1852) ([EDsCODE](https://github.com/EDsCODE))
-   Reset user session after logging in as another user [\#1850](https://github.com/PostHog/posthog/pull/1850) ([macobo](https://github.com/macobo))
-   Fill in person filtering and reintegrate tests [\#1848](https://github.com/PostHog/posthog/pull/1848) ([EDsCODE](https://github.com/EDsCODE))
-   Try running review apps in production mode [\#1847](https://github.com/PostHog/posthog/pull/1847) ([Twixes](https://github.com/Twixes))
-   Bump drf-exceptions-hog to 0.0.3 [\#1845](https://github.com/PostHog/posthog/pull/1845) ([Twixes](https://github.com/Twixes))
-   Experiment: Improving actions UX? [\#1841](https://github.com/PostHog/posthog/pull/1841) ([paolodamico](https://github.com/paolodamico))
-   When DEBUG, include posthog.js with local posthog host [\#1840](https://github.com/PostHog/posthog/pull/1840) ([macobo](https://github.com/macobo))
-   Trim retention query [\#1839](https://github.com/PostHog/posthog/pull/1839) ([EDsCODE](https://github.com/EDsCODE))
-   Add per entity filtering [\#1838](https://github.com/PostHog/posthog/pull/1838) ([EDsCODE](https://github.com/EDsCODE))
-   Disable web snippet on DEBUG instances [\#1837](https://github.com/PostHog/posthog/pull/1837) ([Twixes](https://github.com/Twixes))
-   Fix distinct id too long [\#1831](https://github.com/PostHog/posthog/pull/1831) ([timgl](https://github.com/timgl))
-   Get rid of caching in /decide endpoint [\#1829](https://github.com/PostHog/posthog/pull/1829) ([macobo](https://github.com/macobo))
-   Improve event properties display [\#1825](https://github.com/PostHog/posthog/pull/1825) ([timgl](https://github.com/timgl))
-   Fix tsconfig.json lib property [\#1818](https://github.com/PostHog/posthog/pull/1818) ([mariusandra](https://github.com/mariusandra))
-   Update dockerfile for dev-ing [\#1817](https://github.com/PostHog/posthog/pull/1817) ([fuziontech](https://github.com/fuziontech))
-   Fix email test [\#1814](https://github.com/PostHog/posthog/pull/1814) ([timgl](https://github.com/timgl))
-   Fix status report period [\#1810](https://github.com/PostHog/posthog/pull/1810) ([Twixes](https://github.com/Twixes))
-   Toolbar Shadow Root Support [\#1805](https://github.com/PostHog/posthog/pull/1805) ([mariusandra](https://github.com/mariusandra))
-   Change session query to not collect events [\#1802](https://github.com/PostHog/posthog/pull/1802) ([EDsCODE](https://github.com/EDsCODE))
-   Fix person querying [\#1797](https://github.com/PostHog/posthog/pull/1797) ([timgl](https://github.com/timgl))
-   Add python version to posthog for automated deploys [\#1795](https://github.com/PostHog/posthog/pull/1795) ([fuziontech](https://github.com/fuziontech))
-   Always limit events [\#1794](https://github.com/PostHog/posthog/pull/1794) ([timgl](https://github.com/timgl))
-   Fix ambiguous timestamp ordering [\#1792](https://github.com/PostHog/posthog/pull/1792) ([timgl](https://github.com/timgl))
-   Fix dev docker build [\#1791](https://github.com/PostHog/posthog/pull/1791) ([timgl](https://github.com/timgl))
-   Create CODE_OF_CONDUCT.md [\#1790](https://github.com/PostHog/posthog/pull/1790) ([yakkomajuri](https://github.com/yakkomajuri))
-   Make shared_dashboards endpoint exempt from x-frame-options header [\#1789](https://github.com/PostHog/posthog/pull/1789) ([yakkomajuri](https://github.com/yakkomajuri))
-   Retention date filtering [\#1788](https://github.com/PostHog/posthog/pull/1788) ([EDsCODE](https://github.com/EDsCODE))
-   Search for cohorts that contain the given distinctIDs for feature flags [\#1780](https://github.com/PostHog/posthog/pull/1780) ([fuziontech](https://github.com/fuziontech))
-   Report all non-DRF exceptions to sentry [\#1773](https://github.com/PostHog/posthog/pull/1773) ([paolodamico](https://github.com/paolodamico))
-   Bump posthoganalytics requirement for feature flag bugfixes [\#1772](https://github.com/PostHog/posthog/pull/1772) ([fuziontech](https://github.com/fuziontech))
-   Set heroku python runtime to python 3.8.6 [\#1769](https://github.com/PostHog/posthog/pull/1769) ([fuziontech](https://github.com/fuziontech))
-   Fix sessions team filtering [\#1766](https://github.com/PostHog/posthog/pull/1766) ([timgl](https://github.com/timgl))
-   Add option to delete feature flags [\#1761](https://github.com/PostHog/posthog/pull/1761) ([yakkomajuri](https://github.com/yakkomajuri))
-   Test if any filters exist and if they do make sure there are properties to filter on for decide endpoint [\#1759](https://github.com/PostHog/posthog/pull/1759) ([fuziontech](https://github.com/fuziontech))
-   Fix demo urls [\#1757](https://github.com/PostHog/posthog/pull/1757) ([mariusandra](https://github.com/mariusandra))
-   Change h1 of Live Actions page to "Live Actions" instead of "Events" [\#1756](https://github.com/PostHog/posthog/pull/1756) ([yakkomajuri](https://github.com/yakkomajuri))
-   Fix toolbar fade container click block [\#1753](https://github.com/PostHog/posthog/pull/1753) ([mariusandra](https://github.com/mariusandra))
-   Bump posthog analytics version [\#1751](https://github.com/PostHog/posthog/pull/1751) ([timgl](https://github.com/timgl))
-   Add personal api key [\#1747](https://github.com/PostHog/posthog/pull/1747) ([timgl](https://github.com/timgl))
-   1684 allow ip override [\#1744](https://github.com/PostHog/posthog/pull/1744) ([timgl](https://github.com/timgl))
-   Remove Toolbar Dock Mode [\#1733](https://github.com/PostHog/posthog/pull/1733) ([mariusandra](https://github.com/mariusandra))
-   Use drf-exceptions-hog package [\#1732](https://github.com/PostHog/posthog/pull/1732) ([paolodamico](https://github.com/paolodamico))
-   Disable weekly status report on PostHog Cloud [\#1730](https://github.com/PostHog/posthog/pull/1730) ([Twixes](https://github.com/Twixes))
-   Use Django now for tz aware timestamps [\#1728](https://github.com/PostHog/posthog/pull/1728) ([fuziontech](https://github.com/fuziontech))
-   Use utcnow\(\). Always default to UTC [\#1727](https://github.com/PostHog/posthog/pull/1727) ([fuziontech](https://github.com/fuziontech))
-   Replace uuid4 and uuid1_macless with UUIDT [\#1726](https://github.com/PostHog/posthog/pull/1726) ([Twixes](https://github.com/Twixes))
-   Onboarding improvements [\#1723](https://github.com/PostHog/posthog/pull/1723) ([mariusandra](https://github.com/mariusandra))
-   Self-serve billing enrollment & management [\#1721](https://github.com/PostHog/posthog/pull/1721) ([paolodamico](https://github.com/paolodamico))
-   Improve Django commands for development [\#1720](https://github.com/PostHog/posthog/pull/1720) ([Twixes](https://github.com/Twixes))
-   Do not shadow Kafka default columns \_timestamp and \_offset [\#1718](https://github.com/PostHog/posthog/pull/1718) ([fuziontech](https://github.com/fuziontech))
-   Small insights type update [\#1717](https://github.com/PostHog/posthog/pull/1717) ([mariusandra](https://github.com/mariusandra))
-   Don't assume that each user belongs to a team [\#1715](https://github.com/PostHog/posthog/pull/1715) ([Twixes](https://github.com/Twixes))
-   Fix migration issue [\#1711](https://github.com/PostHog/posthog/pull/1711) ([Twixes](https://github.com/Twixes))
-   Update 0085_org_models.py [\#1710](https://github.com/PostHog/posthog/pull/1710) ([Twixes](https://github.com/Twixes))
-   Fix compatibility with posthog-production [\#1708](https://github.com/PostHog/posthog/pull/1708) ([Twixes](https://github.com/Twixes))
-   Random improvements \(merge people, analytics\) [\#1706](https://github.com/PostHog/posthog/pull/1706) ([paolodamico](https://github.com/paolodamico))
-   Make production docker-compose.yml generated [\#1704](https://github.com/PostHog/posthog/pull/1704) ([Twixes](https://github.com/Twixes))
-   Added docker-compose proxy file [\#1703](https://github.com/PostHog/posthog/pull/1703) ([yakkomajuri](https://github.com/yakkomajuri))
-   Fix Master EE code [\#1701](https://github.com/PostHog/posthog/pull/1701) ([mariusandra](https://github.com/mariusandra))
-   Send a weekly instance status report \(resolves \#1509\) [\#1683](https://github.com/PostHog/posthog/pull/1683) ([Twixes](https://github.com/Twixes))
-   Materialize Views to wrap data coming in from Kafka for Events, Elements, People [\#1678](https://github.com/PostHog/posthog/pull/1678) ([fuziontech](https://github.com/fuziontech))
-   refactor how we grab kafka_host to make it reusable for migrations [\#1677](https://github.com/PostHog/posthog/pull/1677) ([fuziontech](https://github.com/fuziontech))
-   Test if person exists before getting from it [\#1676](https://github.com/PostHog/posthog/pull/1676) ([fuziontech](https://github.com/fuziontech))
-   Make get_is_identified more tolerant of missing person [\#1675](https://github.com/PostHog/posthog/pull/1675) ([fuziontech](https://github.com/fuziontech))
-   Organizations – models [\#1674](https://github.com/PostHog/posthog/pull/1674) ([Twixes](https://github.com/Twixes))
-   Fix table view sessions [\#1672](https://github.com/PostHog/posthog/pull/1672) ([timgl](https://github.com/timgl))
-   Use cached results for funnels [\#1671](https://github.com/PostHog/posthog/pull/1671) ([timgl](https://github.com/timgl))
-   Remove default json serializer from kafka_helper [\#1669](https://github.com/PostHog/posthog/pull/1669) ([fuziontech](https://github.com/fuziontech))
-   Put process_event_ee back on celery with delay [\#1667](https://github.com/PostHog/posthog/pull/1667) ([fuziontech](https://github.com/fuziontech))
-   Show underlying property value type [\#1666](https://github.com/PostHog/posthog/pull/1666) ([Twixes](https://github.com/Twixes))
-   Add detailed label to actionstable [\#1653](https://github.com/PostHog/posthog/pull/1653) ([timgl](https://github.com/timgl))
-   Added warning for changing feature flag key [\#1646](https://github.com/PostHog/posthog/pull/1646) ([yakkomajuri](https://github.com/yakkomajuri))
-   Fix a few "Unchanged files with check annotations" issues [\#1641](https://github.com/PostHog/posthog/pull/1641) ([mariusandra](https://github.com/mariusandra))
-   Add "is_simple_flag" to Feature flags [\#1639](https://github.com/PostHog/posthog/pull/1639) ([timgl](https://github.com/timgl))
-   Fix Cypress tests [\#1635](https://github.com/PostHog/posthog/pull/1635) ([yakkomajuri](https://github.com/yakkomajuri))
-   Upgrade Kea and TypeGen to latest versions [\#1634](https://github.com/PostHog/posthog/pull/1634) ([mariusandra](https://github.com/mariusandra))
-   Nicer API Failure Errors [\#1633](https://github.com/PostHog/posthog/pull/1633) ([mariusandra](https://github.com/mariusandra))
-   Added password strength bar [\#1632](https://github.com/PostHog/posthog/pull/1632) ([yakkomajuri](https://github.com/yakkomajuri))
-   Fix optional trailing slash routing [\#1631](https://github.com/PostHog/posthog/pull/1631) ([Twixes](https://github.com/Twixes))
-   Remove function call to see impact on performance [\#1627](https://github.com/PostHog/posthog/pull/1627) ([fuziontech](https://github.com/fuziontech))
-   Refactor get_or_create_person function in process_event [\#1626](https://github.com/PostHog/posthog/pull/1626) ([fuziontech](https://github.com/fuziontech))
-   Migrate process_event shared functions to be public [\#1625](https://github.com/PostHog/posthog/pull/1625) ([fuziontech](https://github.com/fuziontech))
-   Make hash elements public function on element_group [\#1622](https://github.com/PostHog/posthog/pull/1622) ([fuziontech](https://github.com/fuziontech))
-   Remove Trailing Spaces in Selector Box [\#1621](https://github.com/PostHog/posthog/pull/1621) ([J0](https://github.com/J0))
-   Convert private functions to public for ee access [\#1618](https://github.com/PostHog/posthog/pull/1618) ([fuziontech](https://github.com/fuziontech))
-   Core action tracking I [\#1612](https://github.com/PostHog/posthog/pull/1612) ([paolodamico](https://github.com/paolodamico))
-   Bugfix: Remove celerybeat.pid before starting docker worker [\#1608](https://github.com/PostHog/posthog/pull/1608) ([fuziontech](https://github.com/fuziontech))
-   Skip some tests on multitenancy [\#1607](https://github.com/PostHog/posthog/pull/1607) ([paolodamico](https://github.com/paolodamico))
-   Add tests for FOSS [\#1600](https://github.com/PostHog/posthog/pull/1600) ([timgl](https://github.com/timgl))
-   Typo in licenses.tsx [\#1599](https://github.com/PostHog/posthog/pull/1599) ([jonhyde-legl](https://github.com/jonhyde-legl))
-   Fix: Do not load debug_toolbar when testing [\#1598](https://github.com/PostHog/posthog/pull/1598) ([paolodamico](https://github.com/paolodamico))
-   Bump posthog-js 1.4.5 [\#1597](https://github.com/PostHog/posthog/pull/1597) ([timgl](https://github.com/timgl))
-   Add statsd to celery tasks and add task to monitor queue size [\#1595](https://github.com/PostHog/posthog/pull/1595) ([fuziontech](https://github.com/fuziontech))
-   Papercups identify user [\#1593](https://github.com/PostHog/posthog/pull/1593) ([timgl](https://github.com/timgl))
-   Make /decide endpoint more flexible \(pt. 2\) [\#1592](https://github.com/PostHog/posthog/pull/1592) ([yakkomajuri](https://github.com/yakkomajuri))
-   Revert "Add monitoring of celery queue size to statsd \(\#1589\)" [\#1591](https://github.com/PostHog/posthog/pull/1591) ([fuziontech](https://github.com/fuziontech))
-   Add monitoring of celery queue size to statsd [\#1589](https://github.com/PostHog/posthog/pull/1589) ([fuziontech](https://github.com/fuziontech))
-   Noop on celery worker if ee is not enabled [\#1587](https://github.com/PostHog/posthog/pull/1587) ([fuziontech](https://github.com/fuziontech))
-   Use celery defaults for concurrency, bumping workers only increased latency of event processing [\#1584](https://github.com/PostHog/posthog/pull/1584) ([fuziontech](https://github.com/fuziontech))
-   Increase number of concurrent celery workers in production [\#1583](https://github.com/PostHog/posthog/pull/1583) ([fuziontech](https://github.com/fuziontech))
-   Handle the case of invalid json gracefully [\#1581](https://github.com/PostHog/posthog/pull/1581) ([weyert](https://github.com/weyert))
-   \#724: Export Events to CSV [\#1580](https://github.com/PostHog/posthog/pull/1580) ([michlsemn](https://github.com/michlsemn))
-   Fix and test Team.event_properties_numerical [\#1572](https://github.com/PostHog/posthog/pull/1572) ([Twixes](https://github.com/Twixes))
-   Explicitly use python-statsd as statsd lib [\#1570](https://github.com/PostHog/posthog/pull/1570) ([fuziontech](https://github.com/fuziontech))
-   Remove statsd [\#1568](https://github.com/PostHog/posthog/pull/1568) ([EDsCODE](https://github.com/EDsCODE))
-   Downgrade react dom [\#1559](https://github.com/PostHog/posthog/pull/1559) ([timgl](https://github.com/timgl))
-   Identify email in frontend [\#1558](https://github.com/PostHog/posthog/pull/1558) ([timgl](https://github.com/timgl))
-   Improve API routing [\#1557](https://github.com/PostHog/posthog/pull/1557) ([Twixes](https://github.com/Twixes))
-   Fix multiple elementgroup returned [\#1549](https://github.com/PostHog/posthog/pull/1549) ([timgl](https://github.com/timgl))
-   Fix team uuid migration [\#1548](https://github.com/PostHog/posthog/pull/1548) ([timgl](https://github.com/timgl))
-   Fix property filtering null values [\#1546](https://github.com/PostHog/posthog/pull/1546) ([timgl](https://github.com/timgl))
-   Only allow using aggregate functions on numerical properties [\#1536](https://github.com/PostHog/posthog/pull/1536) ([Twixes](https://github.com/Twixes))
-   Signup improvements [\#1535](https://github.com/PostHog/posthog/pull/1535) ([paolodamico](https://github.com/paolodamico))
-   Changes to make person editable \(resolves \#89\) [\#1491](https://github.com/PostHog/posthog/pull/1491) ([cr33dx](https://github.com/cr33dx))

### 1.14.0 - Thursday 03 September

-   [Insight History](https://github.com/PostHog/posthog/pull/1379)

![Insight History Screenshot](https://posthog-static-files.s3.us-east-2.amazonaws.com/Documentation-Assets/insight-history.png)

Eric really killed this one with a massive pull request where 55 files were modified.

As a result, PostHog now allows you to look through a history of the charts you've made on 'Insights', so that you don't have to worry about forgetting the exact filters you used to reach a certain conclusion, or feeling bad about not having saved that perfect chart from a week ago.

Experiment with insights all you want, now without the fear of losing your work.

-   [Personal API Keys](https://github.com/PostHog/posthog/pull/1281)

![Personal API Keys Screenshot](https://posthog-static-files.s3.us-east-2.amazonaws.com/Documentation-Assets/personal-api.png)

We also merged another huge PR (58 files changed!) from Michael that's been a long time in the making because we wanted to get this just right.

To facilitate integrations with external services, as well as make the experience of using our API simpler and safer, we have now introduced Personal API Keys. They can be generated and deleted on the PostHog setup page. It's worth noting that this is a private API Key, compared to your public 'Team API Key' used in the snippet.

Lastly, because of this change, we have deprecated authentication with username and password for API endpoints.

-   [Public Roadmap](https://github.com/orgs/PostHog/projects/1)

![Public Roadmap Screenshot](https://posthog-static-files.s3.us-east-2.amazonaws.com/Documentation-Assets/public-roadmap.png)

At PostHog, one of our core values is transparency. As a result, we try to make as much information public as we can, from what we're working on to how we operate.

As such, it felt important to us to release a public roadmap where our entire community can view what we're up to, what we'll work on next, and what our objectives are for the future. For a long time we have had a rough roadmap available in our Handbook, but, by now having our roadmap on GitHub, we can directly link issues to the board, and community members can also vote (with emojis 👍) on issues they believe to be important.

Furthermore, we have always encouraged members of our community to open issues for bugs, feature requests, or just anything at all they want to see changed. Now, issues opened by the community can be incorporated on the roadmap, so you can have an idea of how your suggestions fit in with our development process.

Keep the tickets coming!

-   [PostHog FOSS](https://github.com/PostHog/posthog-foss)

As an open core company, we have to conciliate our open source efforts with our ability to generate revenue. Generating revenue is how we're able to continue to sustain our extensive work in the open source space.

Thus, after a lot of brainstorming and [calls with the likes of Sid Sijbrandij](https://posthog.com/blog/a-chat-with-sid), CEO of multibillion dollar [open core company GitLab](https://about.gitlab.com/install/ce-or-ee/), we settled on a business model that allows PostHog to be a sustainable company in the open source space.
c
This led to the creation of two key things: an `ee` subdirectory on our [main repo](https://github.com/PostHog/posthog), and a new repository called [posthog-foss](https://github.com/PostHog/posthog-foss). We'll be explaining these in more detail in the future, but, for now, you should know that to run fully MIT-licensed software, you can either clone the main repo and delete the `ee` subdirectory (without any consequences), or clone our posthog-foss repo, which is a mirror of the main repository without proprietary code.

In addition, if you're an enterprise customer looking for added functionality and improved performance, contact us at sales@posthog.com to discuss the license for using our proprietary features.

-   [Secret Key Requirement](https://github.com/PostHog/posthog/pull/1426)

To ensure the security of your PostHog instance, it's important that you use a randomly-generated unique `SECRET_KEY`. This key is used by Django to encrypt cookies, calculate hashes, and generate tokens, making it of high importance.

Prior to this version, we denoted the importance of this in our Docs, but did not enforce it in our software. Now, to enhance security, PostHog will not allow you to run the server without setting it.

Many of our deployments generate and set this key by default, so that you will not need to worry about it. This is the case with our [Heroku One-Click deployment](https://posthog.com/docs/deployment/deploy-heroku), for example. However, other methods may not automatically do this (we're working on it!). As such, if you run into any issues when updating PostHog, make sure you have a unique `SECRET_KEY` set.

You can find more information about this on our ['Securing PostHog' page](https://posthog.com/docs/configuring-posthog/securing-posthog#secret-key) and should always feel welcome to ask any questions on our [community Slack group](https://join.slack.com/t/posthogusers/shared_invite/enQtOTY0MzU5NjAwMDY3LTc2MWQ0OTZlNjhkODk3ZDI3NDVjMDE1YjgxY2I4ZjI4MzJhZmVmNjJkN2NmMGJmMzc2N2U3Yjc3ZjI5NGFlZDQ).

## Bug Fixes and Performance Improvements

-   We [disabled our own snippet](https://github.com/PostHog/posthog/pull/1539) on DEBUG instances and [improved tracking](https://github.com/PostHog/posthog/pull/1519)
-   We [started using `django_extensions`](https://github.com/PostHog/posthog/pull/1541)
-   Tim added a test to PRs to [check if our Docker image builds](https://github.com/PostHog/posthog/pull/1515/files)
-   [Michael](https://github.com/PostHog/posthog/pull/1537/files) and [a bot](https://github.com/PostHog/posthog/pull/1527) helped us keep dependencies up-to-date
-   Marius made the Toolbar UX better by [fixing its element detection](https://github.com/PostHog/posthog/pull/1424), [making the info window follow the mouse](https://github.com/PostHog/posthog/pull/1472), and [correcting other minor things](https://github.com/PostHog/posthog/pull/1470)
-   Paolo [made user metrics better](https://github.com/PostHog/posthog/pull/1508)
-   Eric [updated our /insights endpoint](https://github.com/PostHog/posthog/pull/1498)
-   We changed the [color on some tabs](https://github.com/PostHog/posthog/pull/1485) and the [tone on some buttons](https://github.com/PostHog/posthog/commit/35e604e031da43b49da0afb0e7a854ecd93c95b8) to improve our UI
-   We [fixed](https://github.com/PostHog/posthog/pull/1514) and then [added tests for our multitenancy environment](https://github.com/PostHog/posthog/pull/1533/)
-   Michael [fixed a UI bug on our URL list](https://github.com/PostHog/posthog/pull/1526)
-   We overhauled our README, which was really in need of updating. It now [looks better](https://github.com/PostHog/posthog/pull/1410), [reads better](https://github.com/PostHog/posthog/pull/1492), and has better info about [deployment](https://github.com/PostHog/posthog/pull/1525) and [our Enterprise Edition](https://github.com/PostHog/posthog/pull/1428).
-   We improved the [command description for `setup_review`](https://github.com/PostHog/posthog/commit/6b209413e9a6ee33b1e21b261ef72593da2b912a)
-   Tim made our [testing of PR environments easier](https://github.com/PostHog/posthog/pull/1496)
-   We made the ['Launch Toolbar' links open on a new page](https://github.com/PostHog/posthog/pull/1524)
-   We [updated our CHANGELOG](https://github.com/PostHog/posthog/pull/1522/files) and bumped versions [here](https://github.com/PostHog/posthog/pull/1421) and [there](https://github.com/PostHog/posthog/pull/1517)(and in a lot of other places)
-   We crushed a bug regarding [rest hooks for Docker images](https://github.com/PostHog/posthog/pull/1516/files)
-   We [improved our syntax highlighting for code snippets](https://github.com/PostHog/posthog/pull/1490)
-   [License issues](https://github.com/PostHog/posthog/pull/1511/files) and [disappearing user paths on Firefox](https://github.com/PostHog/posthog/pull/1513) are now bugs of the past
-   [@J0](https://github.com/J0), a community member, introduced a [feature for disabling link sharing](https://github.com/PostHog/posthog/pull/1475)
-   Michael removed a [useless release drafter action](https://github.com/PostHog/posthog/pull/1476)
-   We had a [small refactor done](https://github.com/PostHog/posthog/pull/1489/files) on PostHog's `head` template
-   Yakko [fixed our Cypress tests](https://github.com/PostHog/posthog/pull/1486) and made them faster
-   We [allowed Sentry in DEBUG mode](https://github.com/PostHog/posthog/pull/1480)
-   We demolished issues with [Safari's funnels](https://github.com/PostHog/posthog/pull/1477) and [IDs for our CohortPeople class](https://github.com/PostHog/posthog/pull/1478)
-   Paolo set up an [awesome Preflight page](https://github.com/PostHog/posthog/pull/1473)
-   We [upgraded the Sentry SDK](https://github.com/PostHog/posthog/pull/1439)
-   We made our [action for syncing FOSS and non-FOSS repositories beautiful](https://github.com/PostHog/posthog/commit/12eeaf999ec7a1594a971ead5fda6dc82adc3c1a)("using prettier")
-   We set up an [action for syncing our FOSS and main repo](https://github.com/PostHog/posthog/pull/1423) then updated it [again](https://github.com/PostHog/posthog/commit/534c25686e1a9fc261230ef669df557cc69fb293) and [again](https://github.com/PostHog/posthog/commit/e9e6e39c189cdf261f91d56267335170c793e52e)
-   We added [regex and action hints for the Toolbar](https://github.com/PostHog/posthog/pull/1457)
-   We [migrated to `BigInteger` IDs](https://github.com/PostHog/posthog/pull/1471/)
-   We changed the Toolbar heatmap to [display number of clicks instead of page rank](https://github.com/PostHog/posthog/pull/1459)
-   We fixed our [bottom notice warning](https://github.com/PostHog/posthog/pull/1467) for PostHog running on HTTP
-   We set up a [workflow for auto-updating the version](https://github.com/PostHog/posthog/pull/1452/)
-   We [improved the description for DAUs](https://github.com/PostHog/posthog/pull/1454)
-   Michael added a [warning bar for production PostHog instances running on HTTP](https://github.com/PostHog/posthog/pull/1437)
-   Anna [fixed a bug with action deletion](https://github.com/PostHog/posthog/pull/1448/)
-   We fixed [an issue with licensing](https://github.com/PostHog/posthog/pull/1438) and [another one](https://github.com/PostHog/posthog/pull/1450)
-   We [fixed our Docker images](https://github.com/PostHog/posthog/pull/1443) to account for changes in Kea and Django's SECRET_KEY
-   Marius upgraded us to [use the newest version of Kea Typegen](https://github.com/PostHog/posthog/pull/1427)
-   Eric pulverized a [bug about empty conditions on Trends](https://github.com/PostHog/posthog/pull/1416)
-   We added a [column to denote when actions were created](https://github.com/PostHog/posthog/pull/1415)
-   We [made the Toolbar easy to launch for all users](https://github.com/PostHog/posthog/pull/1345)

### 1.13.0 – Thursday 13 August

-   [PostHog is Now Available on Segment!](https://posthog.com/blog/posthog-segment-integration)

![](https://raw.githubusercontent.com/posthog/posthog.com/b1b5c23/contents/images/posthog-segment.png)

We're happy to announce that PostHog is now available as a destination on Segment.

Our friends at Segment have built a platform that works as an integrated data pipeline to pull in all your customer data. It's a cool way to combine PostHog with ie Google Analytics or Salesforce data.

If you're already a Segment user, check us out on their [Destination Catalog](https://segment.com/docs/connections/destinations/catalog/). Otherwise, if you're dealing with multiple tools for data collection and analysis, consider using [Segment](https://segment.com/)! They have a generous [startup scheme too](https://segment.com/industry/startups/), like us.

-   [Quicker access to everything](https://github.com/PostHog/posthog/pull/1265)

![](https://user-images.githubusercontent.com/13127476/88422815-ce7a0080-cdb8-11ea-900e-ae60b36745f7.gif)

We consolidated trends, sessions, funnels, retention, and user paths into one page for much faster answers to the questions you may have!

-   [More powerful Slack messages](https://github.com/PostHog/posthog/pull/1219)

![](https://user-images.githubusercontent.com/4550621/89835642-66bc0780-db65-11ea-9203-f08b154f37b0.png)

PostHog has a feature where Actions can be posted to Slack or Microsoft Teams. This helps you notify your team in real time of the user actions that really matter. Just got a new user? Ping your sales team. Did a user try out a new feature? Get an alert!

The integration used to be very basic - but now you can edit the message format directly in the UI.

-   [Toolbars for all!](https://github.com/PostHog/posthog/pull/1326)

![](https://posthog.com/images/3ce1232ef29d0d59b4ac2779d8e97cf8/inspect.gif)

PostHog provides an irrefutably awesome toolbar. This lets you interact with your site or app and understand who is doing what. We've been in Beta for a few weeks, and spent a lot of time interviewing early users - thank you to everyone that took part!

We have now eliminated many bugs and improved the UX, so this feature will be on by default for all new PostHog users.

-   [Better annotations](https://github.com/PostHog/posthog/pull/1331)

![](https://user-images.githubusercontent.com/13127476/89192699-dda83d80-d572-11ea-9ef1-293ea4498cfe.gif)

You can annotate graphs in PostHog - mention big releases, new features, or changes to your UX.

Now, it's quicker and easier to get a quick read on what happened that caused something funky in your graphs.

We've also made all annotations [default to being global](https://github.com/PostHog/posthog/pull/1296). That means if you create an annotation in one graph (or in the annotations page), it is visible across any dashboard graph that covers that date range. No need to fear losing your annotations.

## Bug Fixes and Performance Improvements

-   Heatmaps [now work](https://github.com/PostHog/posthog/pull/1397) for sites built with Tailwind CSS.
-   Some clicks for the heatmap were being double counted. Now [they aren't](https://github.com/PostHog/posthog/pull/1400).
-   We improved the UX for [posting to Slack](https://github.com/PostHog/posthog/pull/1402).
-   We fixed [selector attributes](https://github.com/PostHog/posthog/pull/1413).
-   We made a [security improvement](https://github.com/PostHog/posthog/pull/1387) to the way session cookies are used, and [removed SameSite middleware](https://github.com/PostHog/posthog/pull/1384).
-   We fixed a bug where GitHub actions [required packer](https://github.com/PostHog/posthog/pull/1304) to be manually installed.
-   [Cohorts supported](https://github.com/PostHog/posthog/pull/1362) for people merged to a person.
-   [Solved a bug](https://github.com/PostHog/posthog/pull/1386) with the way the current version update message displayed.
-   If you're running in DEBUG mode, it'll be [more obvious](https://github.com/PostHog/posthog/pull/1378)!
-   We [refactored sessions](https://github.com/PostHog/posthog/pull/1307) into a new queries folder.
-   There was a weird issue with the user email search. [That's gone](https://github.com/PostHog/posthog/pull/1351).
-   We squished [two](https://github.com/PostHog/posthog/pull/1330) [bugs](https://github.com/PostHog/posthog/pull/1348) with our stickiness metrics when specific events were filtered.
-   The team page now [looks much nicer](https://github.com/PostHog/posthog/pull/1346).
-   Eric smushed [a bug](https://github.com/PostHog/posthog/pull/1337) with filters.
-   We [improved how logouts work](https://github.com/PostHog/posthog/pull/1309) with the toolbar.
-   We crushed [a bug](https://github.com/PostHog/posthog/pull/1335) with date filters and funnels.
-   We [improved how StatsD is used](https://github.com/PostHog/posthog/pull/1336) for better tracking of the things that PostHog doesn't track!
-   Chunk loading errors [be gone](https://github.com/PostHog/posthog/pull/1333). The assertive "attempt to" in the title says it all.
-   Saving actions from the toolbar [now makes it easier](https://github.com/PostHog/posthog/pull/1313) to view insights or to go to your actions list.
-   We cleaned up a debug warning, [leveraging heart emojis](https://github.com/PostHog/posthog/pull/1332).
-   An issue with demo data on the dashboard loading has [been disappeared](https://github.com/PostHog/posthog/pull/1334).
-   Tim eliminated an issue [with cumulative graphs](https://github.com/PostHog/posthog/pull/1328).
-   A Sentry error about breakdown filters is now [brown bread](https://github.com/PostHog/posthog/pull/1321) (dead).
-   We now [return an error](https://github.com/PostHog/posthog/pull/1319) for malformed JSONs to the API.
-   We've [converted the toolbar to TypeScript](https://github.com/PostHog/posthog/pull/1306). That always makes for a ridiculously huge pull request. 110 files changed. Noice, noice.
-   We [added a missing migration](https://github.com/PostHog/posthog/pull/1311) for ActionStep URL.
-   [Warnings on running local tests](https://github.com/PostHog/posthog/pull/1308) now don't appear.
-   The experiments tab in the navigation didn't have a highlight. [Now it does](https://github.com/PostHog/posthog/pull/1298). That was weird.
-   We [moved most of the analytics logic](https://github.com/PostHog/posthog/pull/1280) into a `queries` folder. This means it's in one place and in the future will make a ClickHouse integration way easier.

### 1.12.0 - Friday 29 July

-   Shared Dashboards

![](https://posthog.com/static/65d34123d9987988980c13fba2713bf4/c83ae/shared-dashboard.png)

Dashboard on a TV in your office? Want to have a public stats page? Share a dashboard with someone who doesn't have a PostHog account? You can now publicly share a dashboard. Just click "Share Dashboard" and enable sharing. You'll get a link that's publicly accesible.

Changed your mind? You can always disable sharing.

-   Aggregate Functions

![](https://posthog.com/static/118b6779d9282eb411849be82ce16676/44385/aggregate.png)

Want to know the average revenue per user? Want to know the lowest browser version anyone is using? You can now do Sum, Max, Min and Avg calculations on any event property and graph them in trends!

-   Global Annotations

![](https://posthog.com/static/1d927d103ca02ecae58c602008c6eea7/776d3/annotations.png)

Digging through git commits to find out what changed to make the graphs go hay-wire? No more! You can now annotate when something happened (a big release, a bugfix or a launch) and make it super easy for your team-mates to figure out what's going on. Now global.

As part of this, you can now also manage, add and delete annotations from a central screen.

-   Funnel Step Time

![](https://posthog.com/static/3fb04aefb8a907937fed6b98d007bd4f/d52e5/funnel-step-time.png)

You can now see how long it takes users on average to get through steps in a funnel.

-   Regex Filtering

![](https://posthog.com/static/9baa7627f8d3ad7e5149b43f8f5d2358/d54e4/regex.png)

Regex master? Put those skills to use on any property with regex filtering

-   Retention Table Improvements

Previously the retention table was hardcoded to only recognize the `$pageview` event as a retention event. Now, you can select any action or event to measure retention on.

Clicking on any section in the retention table will tell you exactly what users fall in that item.

#### Bug Fixes and Performance Improvements

-   We've added a button [to easily launch the toolbar](https://github.com/PostHog/posthog/pull/1186)
-   We've made line charts more precise by [straightening the lines.](https://github.com/PostHog/posthog/pull/1238)
-   We've enabled interval selection for sessions [too](https://github.com/PostHog/posthog/pull/1241)
-   We're now using Typescript ([1](https://github.com/PostHog/posthog/pull/1297), [2](https://github.com/PostHog/posthog/pull/1286))
-   We've [fixed various issues with annotations(https://github.com/PostHog/posthog/pull/1291)
-   We don't refresh the Events table if you [don't select a property](https://github.com/PostHog/posthog/pull/1285)
-   "All time" date filter [works on funnels again](https://github.com/PostHog/posthog/pull/1252)
-   You can now [delete users from your team(https://github.com/PostHog/posthog/pull/1274)
-   Fixed an issue where timestamps [were displayed incorrectly on sessions](https://github.com/PostHog/posthog/pull/1294)
-   Fixed a bug where selecting "last 48 hours" [wouldn't return results](https://github.com/PostHog/posthog/pull/1264)
-   Fixed issues with funnels loading [on dashboards](https://github.com/PostHog/posthog/pull/1266)
-   [UUIDs are ugly](https://github.com/PostHog/posthog/pull/1255), so we just cut them off rather than wrapping entire lines in the events table
-   [Samcaspus](https://github.com/samcaspus) contributed a little bit of magic: we now automatically adjust your date range if [you change the interval](https://github.com/PostHog/posthog/pull/1253)
-   We added a button to dashboard that allows users to [easily add a new item(https://github.com/PostHog/posthog/pull/1242)
-   enhanced ctrl + click new tab opening feature [](https://github.com/PostHog/posthog/pull/1248)
-   Massively speed up [loading live actions](https://github.com/PostHog/posthog/pull/1182)
-   Fix password validation and improve minimums notice (closes #1197) [](https://github.com/PostHog/posthog/pull/1204)
-   Closes #1180 worker fails if timestamp is invalid [](https://github.com/PostHog/posthog/pull/1181)
-   (abhijitghate)[https://github.com/abhijitghate] contributed an improvement to the way we display DAU's in the graph
-   Fix an issue where [loading sessions would do an entire table scan](https://github.com/PostHog/posthog/pull/1221), and then throw it away
-   [Automatically bind docker-compose 2to port 80](https://github.com/PostHog/posthog/pull/1257) for production deployments
-   -   a bunch of improvements to make local development better! ([1](https://github.com/PostHog/posthog/pull/1290), [2](https://github.com/PostHog/posthog/pull/1288), [3](https://github.com/PostHog/posthog/pull/1272), [4](https://github.com/PostHog/posthog/pull/1293))

### 1.11.0 - Friday 17 July

-   Annotations

![](https://posthog.com/static/1d927d103ca02ecae58c602008c6eea7/c83ae/annotations.png)

-   Cohort filters

![](https://posthog.com/static/9ad08691d6f6c70ae5168ba9fbedf2db/c83ae/cohort-filter.png)

-   Retention table filtering

![](https://posthog.com/static/2a8f824019810bdb6b4459743eddffe0/c83ae/retention-filter.png)

-   Many toolbar fixes.

![heatmap](https://posthog.com/images/429b37ae1bb9cc559ade21c81b56a687/heatmap.gif)

#### Bug fixes and performance improvements

-   Some first-time contributors ran into errors with TemplateDoesNotExist, which [we've solved](https://github.com/PostHog/posthog/pull/1200)
-   Add comprehensive Cypress tests for dashboards [to avoid bugs](https://github.com/PostHog/posthog/pull/1171)
-   Add webpackbar for better [readability while developing](https://github.com/PostHog/posthog/pull/1185)
-   Moves total to the bottom of the pie chart to fix z-index issues [readability while developing](https://github.com/PostHog/posthog/pull/1179)
-   Fix an issue with [filtering on the event type](https://github.com/PostHog/posthog/pull/1168)
-   Add Typescript to the [PostHog frontend codebase](https://github.com/PostHog/posthog/pull/1157)
-   Fix the ability to [delete dashboards](https://github.com/PostHog/posthog/pull/1152)
-   Add support [for LZ-String compression](https://github.com/PostHog/posthog/pull/1058)
-   [Use Black for Python formatting](https://github.com/PostHog/posthog/pull/1136

### 1.10.1 - Thursday 2 July 2020

#### Bugfixes

-   Actually include the version bump when you push a release! 🐛
-   Add flutter docs and reorder flow [#1134](https://github.com/PostHog/posthog/pull/1134)
-   Black all the things! [#1136](https://github.com/PostHog/posthog/pull/1136)

### 1.10.0 - Wednesday 1 July 2020

#### Toolbar

-   It's like inspect element, but for user data.

![inspect](https://posthog.com/images/c9709b954e8ea19cf23a633eb35cac05/inspect.gif)

-   Easily see the ranking of which parts of the page your users are interacting with the most:

![heatmap](https://posthog.com/images/429b37ae1bb9cc559ade21c81b56a687/heatmap.gif)

-   We learned a ton about our product and website within minutes of trying this out.

![toolbar dance](https://posthog.com/images/1f1984b6926d02444eef3148293c72af/dance.gif)

#### Feature flags

-   Feature flags let you roll out changes to users with a certain property, or to a percentage of users, or some combo of the two.

![feature flags](https://posthog.com/static/99083b2fefbe9b348c4150c0964d474e/db910/feature-flags.png)

#### Other exciting, enthralling and invigorating features

-   Flutter Integration. You asked for it and now [it's here](https://posthog.com/docs/integrations/flutter-integration)!
-   Retention page. PostHog already had stickiness, but now there is a table that demonstrates perhaps more clearly how your users are coming back (or not!)

![retention view](https://posthog.com/static/33cdb2d1cd630a44b67da0425ca639e3/dc333/retention-view.png)

-   Better onboarding. We've had a go at redoing how our set up flow works, and will be tracking if it helps more people get through PostHog's own funnel!
-   Platform.sh deployment. A very simple, new and trendy way to get up and running!
-   Porter development. Join the cool kids and do web development in the cloud. Thank you so much to [porter-dev](https://github.com/porter-dev) for creating this PR.
-   Event name filtering. By popular demand, you can now filter the events table by the event name. Happy debugging your implementations!

![filter by event name](https://user-images.githubusercontent.com/1727427/84702990-c7f59f00-af57-11ea-8455-92fb89d9c9ae.png)

#### Bug fixes and performance improvements

-   We are now more privacy friendly - you can [discard IP address data](https://github.com/PostHog/posthog/pull/1081)
-   Added the offer of a [free pairing session](https://github.com/PostHog/posthog/pull/1028) to the contributing guide - ask us!!
-   We fixed a bug with [the start times for the session view](https://github.com/PostHog/posthog/pull/1077)
-   We [improved the ./bin/test command](https://github.com/PostHog/posthog/pull/1074)
-   We now let you [break down users by their properties](https://github.com/PostHog/posthog/pull/1070) (it wasn't working before!)
-   We [sped up the people page](https://github.com/PostHog/posthog/pull/1056) - pro tip: don't load stuff you don't need!
-   We [disabled batching in the snippet](https://github.com/PostHog/posthog/pull/1049), since this helps prevent data loss
-   Fixed a weird bug with [moving from sessions to trends](https://github.com/PostHog/posthog/pull/1039)
-   Fixed [person properties being selected](https://github.com/PostHog/posthog/pull/1040), which was causing some issues with the stats.
-   We now [automatically select hourly](https://github.com/PostHog/posthog/pull/1057) if you're looking at data from just today or yesterday - it was weird otherwise!
-   We turned [today into the last 24 hours](https://github.com/PostHog/posthog/pull/1054) - you can now think of yourself as Jack Bauer
-   The people modal now [has pagination](https://github.com/PostHog/posthog/pull/1042)
-   We [now copy array.js.map](https://github.com/PostHog/posthog/pull/1047) as well as everything else to better debug errors
-   We now [show a warning for old browsers](https://github.com/PostHog/posthog/pull/1046), and feel bad for those in big enterprises that must use them!
-   [Black now added](https://github.com/PostHog/posthog/pull/1043) to post commit hooks, so we don't get crazy all-file reformatting
-   Fixed an issue with [force refreshes for cache](https://github.com/PostHog/posthog/pull/1035) in certain places
-   We [fixed a failing test problem](https://github.com/PostHog/posthog/pull/1036) with team_id
-   Improved [person properties and pagination](https://github.com/PostHog/posthog/pull/976)
-   Solved [a Sentry error](https://github.com/PostHog/posthog/pull/1029) with overly long text
-   We [cleaned the configs for release-drafter](https://github.com/PostHog/posthog/pull/1088)

### 1.9.0 - Thursday 18 June 2020

-   [Sessions view](https://github.com/PostHog/posthog/pull/926)
    ![sessions overview](https://posthog.com/static/bdce507cbee394ad12a0a86695889f5f/2cefc/sessions-overview.png)
-   You can then see exactly how a user interacted with your app:
    ![sessions more detail](https://posthog.com/static/c4fe51ff11bbe87eb64c00daf7cc3d78/efc66/session-broken-out.png)
    This should really help with debugging, or just trying to get a detailed view of what users are up to.

#### Better testing

-   [Fixed Cypress tests](https://github.com/PostHog/posthog/pull/1015)
-   Enabled [running cypress in parallel](https://github.com/PostHog/posthog/pull/959), which saved a minute.
-   [Fixed cypress linting errors and sped up tests further](https://github.com/PostHog/posthog/pull/865)
-   [Cached PostHog's yarn builds](https://github.com/PostHog/posthog/pull/927), which took e2e tests down by around 30%.
-   Finally, we now [wait for PostHog to start serving requests](https://github.com/PostHog/posthog/pull/920) rather than the 60 second sleep when running Cypress.

[Develop PostHog with Porter](https://posthog.com/docs/developing-locally#using-porter)

[Management command for millions of events](https://github.com/PostHog/posthog/pull/475)

[Set properties to anonymous users](https://github.com/PostHog/posthog-js/pull/43)

#### Bug fixes and performance improvements

-   We worked hard on improving caching to speed things up. We [fixed cache refreshing](https://github.com/PostHog/posthog/pull/1035) in a few areas, we made a few [caching adjustments](https://github.com/PostHog/posthog/pull/1023) to fix #1022. Finally, we now use [redis to cache results](https://github.com/PostHog/posthog/pull/972).
-   Save time! You can now [create actions from the trends page](https://github.com/PostHog/posthog/pull/990).
-   [Upgrade to posthog-js 1.2.0 to support dynamic params](https://github.com/PostHog/posthog/pull/957).
-   We fixed long href inserts - the href [can now go up to 2048 characters](https://github.com/PostHog/posthog/pull/1027) before truncation. Someone must have had some funky urls going on…
-   [We prevented intermittent issues with yarn build](https://github.com/PostHog/posthog/pull/1026)
-   We [fixed a bug](https://github.com/PostHog/posthog/pull/1021) that caused cohorts to fail when actions were deleted
-   We [solved a problem](https://github.com/PostHog/posthog/pull/980) with comparing trend sessions distribution
-   We [added a limit to number of returned entities for breakdowns](https://github.com/PostHog/posthog/pull/1008) so queries don't time out
-   We [created a fix](https://github.com/PostHog/posthog/pull/1013) for an issue with heartbeats
-   We [made it clearer](https://github.com/PostHog/posthog/pull/1014) that PostHog SaaS users are on the latest version
-   We [slashed CPU consumption for VSCode](https://github.com/PostHog/posthog/pull/1007) by excluding a folder
-   Generated a [performance improvement for element stats](https://github.com/PostHog/posthog/pull/991)
-   We [stopped giving way too many decimal points](https://github.com/PostHog/posthog/pull/984) on our graphs!
-   Trends page [UX improvement](https://github.com/PostHog/posthog/pull/919)
-   [Improved filtering](https://github.com/PostHog/posthog/pull/986) on elements
-   We fixed [a race condition](https://github.com/PostHog/posthog/pull/973/commits/953af2326dff94e8ae1d75cd6ea0fc2c64567857)
-   [We don't rely](https://github.com/PostHog/posthog/pull/949) on \$ to separate PostHog's events
-   We [removed the redundant math selector](https://github.com/PostHog/posthog/pull/950) on funnels - it didn't do anything!
-   [Django upgraded to 3.0.7](https://github.com/PostHog/posthog/pull/932)
-   We [made HTTPS work locally](https://github.com/PostHog/posthog/pull/910) - we had lots of community issues raised, so that should make it easier to get started with!
-   We [improved the setup overlay layout](https://github.com/PostHog/posthog/pull/904)
-   We [sped up the events endpoint](https://github.com/PostHog/posthog/pull/903) by just hitting the current week's partitions
-   We solved a problem [with temporary tokens](https://github.com/PostHog/posthog/pull/909)
-   We added [webpack HMR](https://github.com/PostHog/posthog/pull/878) and hashes to chunk filenames. (#878)

### 1.8.0 - Wednesday 3 June 2020

-   [Cumulative graphs](https://github.com/PostHog/posthog/pull/862)

![cumulative graphs](https://posthog.com/images/bfe6baa6ab1a5cac9ca7a74a9d920a7c/cumulative-graph.gif)

-   [More powerful paths](https://github.com/PostHog/posthog/pull/897)

![Paths start point](https://posthog.com/static/07bcede22293f441670c690377152f77/49898/paths-start-point.jpg)

![Paths filtering by properties](https://posthog.com/static/2738ad9eea88ccc59e09a22d5f65d80d/86f7d/paths-filtering.jpg)

-   [Add property filters to actions + lots of improvements (#841)](https://github.com/PostHog/posthog/pull/841)

![Actions property filter](https://posthog.com/static/f4099601731f26a7d1f98a2b8fa9378d/fbd2c/actions-property-filter.jpg)

-   We cleaned up descriptions in the [breakdown filter](https://github.com/PostHog/posthog/pull/886).
-   The [UX is nicer](https://github.com/PostHog/posthog/pull/863) for selection a URL on creating an action.
-   We made it simpler to understand [how to use custom events](https://github.com/PostHog/posthog/pull/873) during the setup process.
-   The token issues, oh the token issues. [Fixed](https://github.com/PostHog/posthog/pull/909) and [fixed](https://github.com/PostHog/posthog/pull/894).
-   It was time for our events table [to become Ant Designed](https://github.com/PostHog/posthog/pull/895).
-   Pre-2020 events [won't affect partitions](https://github.com/PostHog/posthog/pull/875) any more.
-   [Better debugging](https://github.com/PostHog/posthog/pull/854) with Sentry.
-   Scrollbar [small issue be gone](https://github.com/PostHog/posthog/pull/900).
-   We [improved](https://github.com/PostHog/posthog/pull/885) how empty funnels work.
-   Events are [40ms faster to process](https://github.com/PostHog/posthog/pull/833) - 25% quicker!
-   The sidebar [works properly on mobile](https://github.com/PostHog/posthog/pull/839) - no more squished interface on your cell phone.
-   Fix a bug with [selecting filters](https://github.com/PostHog/posthog/pull/844)
-   [Funnels are simpler](https://github.com/PostHog/posthog/pull/881).
-   [Solved](https://github.com/PostHog/posthog/pull/874) a tricky bug on app.posthog.com caused by URLs with non-utf8 or raw binary query parameters.
-   Nothing to do with [dubious cheese](https://www.babybel.com/welcome), we [fixed errors with babel](https://github.com/PostHog/posthog/pull/861)
-   [Improved toolbar UX](https://github.com/PostHog/posthog/pull/890) for actions to fix a small [issue](https://github.com/PostHog/posthog/issues/889).
-   PostHog will now [cache SQL and parameters between events processing](https://github.com/PostHog/posthog/pull/845). This speeds things up by a further 40%.
-   We [refactored more classes to hooks](https://github.com/PostHog/posthog/pull/898), fixing a bug with event name labels along the way.

### 1.7.0 - Wednesday 27 May 2020

-   [Reactive Native](https://github.com/PostHog/posthog-react-native)
-   [Comparison charts](https://github.com/PostHog/posthog/pull/824)

![Comparison charts](https://posthog.com/images/8fe8e9e7c6ac033b80ba06f9c3f36f98/side-by-side-comparison.gif)

-   [Tooltip: View the users inside each datapoint](https://github.com/PostHog/posthog/pull/830/commits/64e1ef34b5d8565934b1980d33432cef4e7002f7)

![Hover breakdown](https://posthog.com/static/5a29596c659e08c983fe803abd607f21/2cefc/hover-breakdown.png)

-   [Property keys explained](https://github.com/PostHog/posthog/pull/822)

![property keys with explanations](https://user-images.githubusercontent.com/1727427/82579579-ed280500-9b85-11ea-92fe-6e7fe67c9d86.png)

-   [Automatic domain detection](https://github.com/PostHog/posthog/pull/815)

![automatic domain detection](https://user-images.githubusercontent.com/1727427/82486899-72071600-9ad5-11ea-8bd1-2f589cc69d34.png)

-   Developing PostHog is now a bit less tedious. We [halved the time](https://github.com/PostHog/posthog/pull/826) it takes to install python dependencies for any deployment.
-   We've written [a lot of front end tests](https://github.com/PostHog/posthog/pull/802), as well as a [regression test](https://github.com/PostHog/posthog/pull/819) for single step funnels, where there was a bug - [now fixed](https://github.com/PostHog/posthog/pull/817).
-   We neatened dashboard items so they're [closer together](https://github.com/PostHog/posthog/pull/846) in the navigation.
-   We [improved our Sentry setup](https://github.com/PostHog/posthog/pull/842).
-   Marius [fixed the way tables display](https://github.com/PostHog/posthog/pull/838) when they're on a dashboard.
-   Eric [slayed a bug](https://github.com/PostHog/posthog/pull/832) when the People page wouldn't load with entity specific filters applied.
-   We've had several users with very high scale pushing the limits of redis. We have more work to do here, but we've [improved the way we handle filled up servers](https://github.com/PostHog/posthog/pull/825).
-   A little [header spring cleaning](https://github.com/PostHog/posthog/pull/831).
-   We [fixed a bug](https://github.com/PostHog/posthog/pull/835) with suggestions loading, and another with [EditAppUrls null check](https://github.com/PostHog/posthog/pull/829).
-   Cohort property filters had a small issue, [now fixed](https://github.com/PostHog/posthog/pull/828).
-   AntD's gradual takeover of our app and website continued - it was [added to more dropdowns](https://github.com/PostHog/posthog/pull/814) this week.
-   We prevented requests to update server for those who have opted out, and [added fine grained control](https://github.com/PostHog/posthog/pull/821) to the opt out flow.

### 1.6.0 - Wednesday 20 May 2020

-   [Dashboard presentation mode](https://github.com/PostHog/posthog/pull/753)

![](https://posthog.com/static/6c585ad804ad3855cf916b530a99e9d0/05ed2/presentation-mode.png)

-   [Dashboard resizing](https://github.com/PostHog/posthog/pull/746)

![](https://posthog.com/images/a73d77c1d5e05f0a5337acc967b178ce/dashboards-moving.gif)

-   [Paths works with events](https://github.com/PostHog/posthog/pull/692)

![](https://posthog.com/images/91e2b9a8274bfba62fda39dc31cf0fb7/paths-with-events.gif)

-   [Dashboard mobile support](https://github.com/PostHog/posthog/pull/775)
-   [Microsoft Teams support](https://posthog.com/docs/integrations/microsoft-teams)
-   [You can now use](https://github.com/PostHog/posthog/pull/768) the django-debug-toolbar to diagnoze performance issues better
-   We added [ES Lint](https://eslint.org/), for JavaScript linting.
-   We fixed [property filter array issue](https://github.com/PostHog/posthog/pull/769)
-   [Optimize funnel rendering](https://github.com/PostHog/posthog/pull/792) is a major improvement in speed for those with many events - now 1 order of magnitude faster.
-   [Multiple filters with same key](https://github.com/PostHog/posthog/pull/738), fixed a bug that means you can now have multiple filters that are the same ie $current_url doesn't equal A and $current_url doesn't equal B
-   [Event partioning](https://github.com/PostHog/posthog/pull/733), which speeds up trends and paths pages in particular. Learn more about [scaling PostHog](https://posthog.com/docs/scaling-posthog).
-   The component Deletewithundo wasn't working because of property mixup, [now it is](https://github.com/PostHog/posthog/pull/750)!
-   [Funnels](https://github.com/PostHog/posthog/pull/751) and [Actions](https://github.com/PostHog/posthog/pull/757) now use Ant Design
-   We temporarily [removed stickiness breakdowns](https://github.com/PostHog/posthog/pull/774), as they were causing issues.
-   [Better handling of breakdown views](https://github.com/PostHog/posthog/pull/758) when users don't have the property.
-   [Fixed an issue](https://github.com/PostHog/posthog/pull/725) with viewing certain queries over all time.
-   [Resolved an issue](https://github.com/PostHog/posthog/pull/748) with sessions where null conditions were missing
-   Fixed the [cohort input search](https://github.com/PostHog/posthog/pull/785) bug
-   Solved [a bug with navigating to users](https://github.com/PostHog/posthog/issues/794)
-   [Improved our event insertion scalability](https://github.com/PostHog/posthog/pull/797)

### 1.5.0 - Wednesday 13 May 2020

-   [Multiple dashboards](https://github.com/PostHog/posthog/pull/740)
    ![](https://posthog.com/changelog/multiple-dashboards.png)
-   [Dark-er mode](https://github.com/PostHog/posthog/pull/740)
    ![](https://posthog.com/changelog/dark-sidebar.png)
-   [Break down by cohort](https://github.com/PostHog/posthog/pull/690)
    ![](https://posthog.com/changelog/breakdown-cohort.png)

-   [Big refactor of how we do routing in the app](https://github.com/PostHog/posthog/pull/717) which means going backwards and forwards should work a lot smoother
-   [Faster loading of paths](https://github.com/PostHog/posthog/pull/729)
-   [More accurate DAU/uniques count](https://github.com/PostHog/posthog/pull/734)
-   [Fix dotted line appearing on completed days](https://github.com/PostHog/posthog/pull/735). Thanks [Jujhar](https://github.com/Jujhar)!

### 1.4.0 - Wednesday 6 May 2020

-   Added filtering of properties individually. For both trends and funnels, you can now add filters for each event/action individually
    ![events](https://posthog.com/wp-content/uploads/2020/05/captured.gif)

-   Added Breakdown by properties in graph.
    ![graph](https://posthog.com/wp-content/uploads/2020/05/captured-1.gif)

-   Session time series, you can now see how time spend in your app changes over time
    ![session time series](https://posthog.com/wp-content/uploads/2020/05/Screenshot-2020-05-06-at-10.59.34.png)

-   Export cohorts as CSV
    ![export cohorts](https://posthog.com/wp-content/uploads/2020/05/Screenshot-2020-05-06-at-10.53.26.png)

-   Edit frontend selector for actions in PostHog
    ![frontend selector](https://posthog.com/wp-content/uploads/2020/05/Screenshot-2020-05-06-at-10.56.03.png)

-   Setup page redesign
    ![setup page redesign](https://posthog.com/wp-content/uploads/2020/05/Screenshot-2020-05-06-at-11.13.06.png)

-   Restrict access to instance by IP address (#679, #682)
-   Fix today + hourly filtering not working (#700)
-   Fix timestamps if users had wrong dates set locally (#693, #697, #699)
-   Add \$screen to events table (#681)
-   Add noindex to login/signup screens (#702)
-   Speed up cohorts page and use antd (#706)

### 1.3.0 - Wednesday 29 April 2020

-   We have added an Android library so you can now capture events in your Android app and send them to PostHog, we can automatically capture screen changes, and send any other events that you like

![android events](https://posthog.com/wp-content/uploads/2020/04/android-events.gif)

-   There is now, also a [PostHog Gatsby plugin](https://posthog.com/docs/integrations/gatsby-integration)

-   We have added URL wildcards so you can use % as a wildcard when setting up an action

![url wildcards](https://posthog.com/wp-content/uploads/2020/04/Posthog-19-e1588157571429.png)

-   We have also updated the Trends page design as well as adding trends info hints. Trends is the default homepage when logging into PostHog.

![trend layout](https://posthog.com/wp-content/uploads/2020/04/Posthog-21-e1588171341976.png)

![trend hints](https://posthog.com/wp-content/uploads/2020/04/Fullscreen_4_29_20__12_09_PM-e1588158606164.png)

-   The Events table can now be sorted by timestamp.

![timestamp reverse](https://posthog.com/wp-content/uploads/2020/04/timestampreverse.gif)

-   Added a more strict flake8 setup and improvements
-   Upgraded Kea to `2.0.0-beta.5`
-   Implemented AntD into Setup page
-   You can now allow access to your PostHog instance by IP address for more security. this does not apply to the JS snippet or the event capture API
-   Added model for typing of filters
-   Added copy code to clipboard changes
-   Use forward for header in middleware if applicable
-   Move get_ip_address to utils
-   Fixed redirect to be explicit for /Trends
-   Moved models to separate files
-   Added link to docs for local deployment
-   Warn instead of crash on invalid selector when using the front-end toolbar

#### Bug Fixes

-   Fixed issue with default trends route
-   Fixed Setup page operations not working
-   Fixed crash when hovering over events
-   Fixed issues with \$create_alias when users have multiple distinct_ids attached to them
-   Fixed trends save to dashboard issue
-   Fixed adding dashboarditem with set dates

### 1.2.0 - Wednesday 22 Aptil 2020

-   We have added an iOS library so you can now capture events in your iOS app and send them to PostHog, we can automatically capture screen changes, and send any other events that you like

Click [here](https://posthog.com/docs/integrations/ios-integration) for instructions on how to install it on your app.

-   We have added Sessions to /trends with two modes: “Average session length”, which shows you how long sessions are and how many, and “distribution” which makes it super easy to spot whether sessions are uniformly distributed or whether there are outliers

![sessions gif](https://posthog.com/wp-content/uploads/2020/04/Sessions.gif)

-   Funnels can be filtered by properties

![Funnel properties](https://posthog.com/wp-content/uploads/2020/04/funnel-properties.gif)

-   Added indexes so loading /trends is super fast, even with millions of events
-   We have offloaded storing events to workers, so that calls to our events API are non-blocking, and you can scale insertion of events independently from the rest of PostHog
-   Removed drf-yasg in favor of our own hosted docs
-   Added layout/header components of Ant design
-   Updated property filters to be "tokenized"
-   Updated the way we display actions/events in trend graphs if those action/events have no data in a given timeframe
-   Updated property filters so that they 'AND' rather than 'OR' if you filter multiples

#### Bug Fixes

-   Fixed unable to sign up to teams
-   Fixed stickniess not loading
-   Fixed property filter bug that would break when multiples were applied in some circumstances
-   Fixed setting event name in action
-   Fixzed event filtering with teams

### 1.1.0.1 - Thursday 16 April 2020

-   Fix issues with custom events while creating actions

### 1.1.0 - Wednesday 15 April 2020

Important! We've added Celery workers. We'll move tasks to workers to speed up a lot of actions in PostHog. [See update instructions](https://posthog.com/docs/deployment/upgrading-posthog#upgrading-from-before-1011) on how to enable workers.

-   Users can integrate PostHog with Slack to send push notifications when events are triggered

![Slack action](https://posthog.com/wp-content/uploads/2020/04/Slack-action.gif)

-   Funnels can now be filtered by Events not just Actions
-   Funnels can be filtered by time intervals as well

![funnel intervals](https://posthog.com/wp-content/uploads/2020/04/funnels-by-time.gif)
![funnel with events](https://posthog.com/wp-content/uploads/2020/04/funnel-with-events.gif)

-   Added Ant Design to PostHog

![ant design sidebar](https://posthog.com/wp-content/uploads/2020/04/Posthog-6-e1586882580994.png)
![ant design buttons](https://posthog.com/wp-content/uploads/2020/04/Posthog-10.png)

-   Trends can now be filtered by different time intervals

![time intervals](https://posthog.com/wp-content/uploads/2020/04/time-intervals.gif)

-   Added dotted lines to represent data yet to be determined

![Dotted line example](https://posthog.com/wp-content/uploads/2020/04/dotted-lines.png)

-   Trends graphs have fixed the X axis at 0

![x axis 0](https://posthog.com/wp-content/uploads/2020/04/Posthog-7.png)

-   Daily Active Users (DAUs) added as a default dashboard

![DAU dahsboard](https://posthog.com/wp-content/uploads/2020/04/Posthog-8.png)

-   Changed the way we rendered urls in Paths to reflect better on different screen sizes

![paths](https://posthog.com/wp-content/uploads/2020/04/Posthog-9.png)

-   Updated UX when saving actions to be clearer

![actions save](https://posthog.com/wp-content/uploads/2020/04/save-actions-ux.gif)

-   Changed the way we store events properties, we now store all event names and property names against the Team
-   Refactored PropertyFilters into a function
-   Added filter by event name to event properties
-   Added mypy rules
-   Using dateutil for datetime
-   Added timestamp index to allow event tables to load at large volumes
-   Updated helm charts to work with redis and workers
-   Added a Babel plugin to reduce antd module load
-   We now use offset instead of timestamp of posthog-js to avoid the wrong user time - previously if your local machine had a time set different to your location (or if the time was just off) we would have displayed that time.
-   Using npm instead of yarn in copy command as Heroku doesn't have yarn
-   We now use posthog-js to get array.js
-   Removed unused indexes from migrations
-   Updated PostHog snippet

#### Bug Fixes

-   Removed unused future import to prevent Heroku deployments breaking
-   Fixed dupliucated users in Cohorts
-   Type Migration to prevent /trend bug when navigating to a url from a dashboard
-   Added missing type in initial dahsboard element creattion to fix the same bug as above
-   Fixed collectstatic on fresh Heroku updates
-   Fixed network timeout yarn for antd
-   Fixed npm command to copy array.js
-   Fixed date filter not detecting moment
-   Fixed redis error when upgrading Heroku
-   Stopped throwing an error if a user doesn't have a distinct id
-   Fixed a trends people bug that ignored the time interval selected
-   Fixed site_url pass to slack from request

### 1.0.11 - Wednesday 8 April 2020

Important! We've added Celery workers. We'll move tasks to workers to speed up a lot of actions in PostHog. [See update instructions](https://posthog.com/docs/deployment/upgrading-posthog#upgrading-from-before-1011) on how to enable workers.

-   Users can filter the trends view by any event rather than just actions

![events in trends](https://posthog.com/wp-content/uploads/2020/04/events-in-trends.gif)

-   Users can now change password in /setup

![password change](https://posthog.com/wp-content/uploads/2020/04/Posthog-3.png)

-   Users can also reset password at login screen
-   Added a logout button

![logout button](https://posthog.com/wp-content/uploads/2020/04/logoutbuton.gif)

-   Added GitHub / GitLab Social Authorization

![social auth](https://posthog.com/wp-content/uploads/2020/04/Posthog-1.png)

-   Added Stickiness explanation in /trends > Shown As > Stickiness

![Stickiness explanation](https://posthog.com/wp-content/uploads/2020/04/Posthog-4.png)

-   Precalculated events that matched actions, this massively speeds up anything that uses actions
-   Added Celery background workers
-   Added gunicorn workers in docker-server script
-   Added email opt in for PostHog Security and Feature updates
-   Removed yarn cache in production image
-   Cleaned docker yarcn cache
-   Reduced size of Docker images by ~80MB
-   Set default password for postgres in docker-compose.yml
-   Sped up the event insert by only loading actions that were really necessary
-   Migrated ip field to event property
-   Updated all links to point to new docs domain
-   Added GitLab API url
-   Added Async JS snippet
-   Docker and server updates for helm

#### Bug Fixes

-   Fixed some instances of Cohort page hangs
-   Fixed demo actions not being recalculated
-   Fixed breakdown error on DAUs where tables could not be filtered
-   Fixed array.js
-   Fixied ActionStep.url\_ so that it can be null

### 1.0.10.2 - Friday 3 April 2020

-   Precalculate Actions to speed up everything (dashboards/actions overview etcetera)
-   Fix error running Docker file

### 1.0.10.1 - Wednesday 1 April 2020

-   Fixes for Helm charts

### 1.0.10 - Wednesday 1 April 2020

-   Users can now be identified directly from Trend Graphs

![users in trend graph](https://posthog.com/wp-content/uploads/2020/03/usersintrends.gif)

-   Added demo data to new instances of /demo

![demo data copy](https://posthog.com/wp-content/uploads/2020/03/HogFlix.png)

-   Built a Helm Chart for PostHog

-   Ordering is now by timestamp instead of id

-   Fixed typing errors

-   Fixed funnels not working if order was set incorrectly

-   Avoided team leakage of person properties

-   Fixed live actions error that resulted in opening multiple events

### 1.0.9 - Wednesday 25 March 2020

-   Stickiness now shown on Trend Graph

![stickiness](https://posthog.com/wp-content/uploads/2020/03/stickiness-gif.gif)

-   Funnel builder changes

![funnel builder](https://posthog.com/wp-content/uploads/2020/03/newfunnel.gif)

-   Changed 'Add event property filter' to 'Filter events by property'.

-   Added drop down to all filters for event properties

![filters](https://posthog.com/wp-content/uploads/2020/03/Posthog-23.png)

-   Added '\_isnot' and 'does not contain' to properties filters

![doesnotcontain](https://posthog.com/wp-content/uploads/2020/03/isnotdoesnotcontain.gif)

-   Moved API key to it's own box

-   Various performance updates

-   Bug fixes

### 1.0.8.2 - Wednesday 18 March 2020

-   Fixes bug where events wouldn't be filtered under /person or /action.

### 1.0.8 - Wednesday 18 March 2020

-   Moved actions into /event submenu

![moved action](https://posthog.com/wp-content/uploads/2020/03/Posthog-3.png)

-   Improved Actions Creation

![improved actions creation](https://posthog.com/wp-content/uploads/2020/03/newtoolbar.gif)

-   Delete user data

![delete user data](https://posthog.com/wp-content/uploads/2020/03/Posthog-4.png)

-   Various performance improvements

-   Bug fixes

-   Turbolinks: Support for navigating between pages with the toolbar open

### 1.0.7 - Wednesday 10 March 2020

-   Added changelog and reminder to update to app.
-   Filtering action trends graphs

![filtering action trends gif](https://posthog.com/wp-content/uploads/2020/03/Action-trend-filter-gif.gif)

-   Exact/contains matching for URLs in actions

![exact/contains matching gif](https://posthog.com/wp-content/uploads/2020/03/image-2.png)

-   Filtering paths by date

![Filtering paths by date](https://posthog.com/wp-content/uploads/2020/03/Path-by-date-gif.gif)

-   Graphs show numbers

![graph show numbers](https://posthog.com/wp-content/uploads/2020/03/image-1.png)

-   Allow multiple URLS when creating actions

![Multiple urls when creating actions](https://user-images.githubusercontent.com/53387/76166375-54751200-615e-11ea-889f-d0ec93356cf2.gif)

-   Better property filters

![image](https://user-images.githubusercontent.com/1727427/76364411-5831a180-62e2-11ea-81f1-f0c1832b7927.png)

-   **API change** If you're using the trends api, filtering by action ID is deprecated in favour of `api/action/trends?action=[{"id":1}]`
