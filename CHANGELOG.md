# Changelog

### 1.13.0 – Thursday 13 August

- [PostHog is Now Available on Segment!](/blog/posthog-segment-integration)

![](https://raw.githubusercontent.com/posthog/posthog.com/b1b5c23/contents/images/posthog-segment.png)

We're happy to announce that PostHog is now available as a destination on Segment.

Our friends at Segment have built a platform that works as an integrated data pipeline to pull in all your customer data. It's a cool way to combine PostHog with ie Google Analytics or Salesforce data.

If you're already a Segment user, check us out on their [Destination Catalog](https://segment.com/docs/connections/destinations/catalog/). Otherwise, if you're dealing with multiple tools for data collection and analysis, consider using [Segment](https://segment.com/)! They have a generous [startup scheme too](https://segment.com/industry/startups/), like us.


- [Quicker access to everything](https://github.com/PostHog/posthog/pull/1265)

![](https://user-images.githubusercontent.com/13127476/88422815-ce7a0080-cdb8-11ea-900e-ae60b36745f7.gif)

We consolidated trends, sessions, funnels, retention, and user paths into one page for much faster answers to the questions you may have!

- [More powerful Slack messages](https://github.com/PostHog/posthog/pull/1219)

![](https://user-images.githubusercontent.com/4550621/89835642-66bc0780-db65-11ea-9203-f08b154f37b0.png)

PostHog has a feature where Actions can be posted to Slack or Microsoft Teams. This helps you notify your team in real time of the user actions that really matter. Just got a new user? Ping your sales team. Did a user try out a new feature? Get an alert!

The integration used to be very basic - but now you can edit the message format directly in the UI.

- [Toolbars for all!](https://github.com/PostHog/posthog/pull/1326)

![](https://posthog.com/images/3ce1232ef29d0d59b4ac2779d8e97cf8/inspect.gif)

PostHog provides an irrefutably awesome toolbar. This lets you interact with your site or app and understand who is doing what. We've been in Beta for a few weeks, and spent a lot of time interviewing early users - thank you to everyone that took part!

We have now eliminated many bugs and improved the UX, so this feature will be on by default for all new PostHog users.

- [Better annotations](https://github.com/PostHog/posthog/pull/1331)

![](https://user-images.githubusercontent.com/13127476/89192699-dda83d80-d572-11ea-9ef1-293ea4498cfe.gif)

You can annotate graphs in PostHog - mention big releases, new features, or changes to your UX.

Now, it's quicker and easier to get a quick read on what happened that caused something funky in your graphs.

We've also made all annotations [default to being global](https://github.com/PostHog/posthog/pull/1296). That means if you create an annotation in one graph (or in the annotations page), it is visible across any dashboard graph that covers that date range. No need to fear losing your annotations.

## Bug Fixes and Performance Improvements

* Heatmaps [now work](https://github.com/PostHog/posthog/pull/1397) for sites built with Tailwind CSS.
* Some clicks for the heatmap were being double counted. Now [they aren't](https://github.com/PostHog/posthog/pull/1400).
* We improved the UX for [posting to Slack](https://github.com/PostHog/posthog/pull/1402).
* We fixed [selector attributes](https://github.com/PostHog/posthog/pull/1413).
* We made a [security improvement](https://github.com/PostHog/posthog/pull/1387) to the way session cookies are used, and [removed SameSite middleware](https://github.com/PostHog/posthog/pull/1384).
* We fixed a bug where GitHub actions [required packer](https://github.com/PostHog/posthog/pull/1304) to be manually installed.
* [Cohorts supported](https://github.com/PostHog/posthog/pull/1362) for people merged to a person.
* [Solved a bug](https://github.com/PostHog/posthog/pull/1386) with the way the current version update message displayed.
* If you're running in DEBUG mode, it'll be [more obvious](https://github.com/PostHog/posthog/pull/1378)!
* We [refactored sessions](https://github.com/PostHog/posthog/pull/1307) into a new queries folder.
* There was a weird issue with the user email search. [That's gone](https://github.com/PostHog/posthog/pull/1351).
* We squished [two](https://github.com/PostHog/posthog/pull/1330) [bugs](https://github.com/PostHog/posthog/pull/1348) with our stickiness metrics when specific events were filtered.
* The team page now [looks much nicer](https://github.com/PostHog/posthog/pull/1346).
* Eric smushed [a bug](https://github.com/PostHog/posthog/pull/1337) with filters.
* We [improved how logouts work](https://github.com/PostHog/posthog/pull/1309) with the toolbar.
* We crushed [a bug](https://github.com/PostHog/posthog/pull/1335) with date filters and funnels.
* We [improved how StatsD is used](https://github.com/PostHog/posthog/pull/1336) for better tracking of the things that PostHog doesn't track!
* Chunk loading errors [be gone](https://github.com/PostHog/posthog/pull/1333). The assertive "attempt to" in the title says it all.
* Saving actions from the toolbar [now makes it easier](https://github.com/PostHog/posthog/pull/1313) to view insights or to go to your actions list.
* We cleaned up a debug warning, [leveraging heart emojis](https://github.com/PostHog/posthog/pull/1332).
* An issue with demo data on the dashboard loading has [been disappeared](https://github.com/PostHog/posthog/pull/1334).
* Tim eliminated an issue [with cumulative graphs](https://github.com/PostHog/posthog/pull/1328).
* A Sentry error about breakdown filters is now [brown bread](https://github.com/PostHog/posthog/pull/1321) (dead).
* We now [return an error](https://github.com/PostHog/posthog/pull/1319) for malformed JSONs to the API.
* We've [converted the toolbar to TypeScript](https://github.com/PostHog/posthog/pull/1306). That always makes for a ridiculously huge pull request. 110 files changed. Noice, noice.
* We [added a missing migration](https://github.com/PostHog/posthog/pull/1311) for ActionStep URL.
* [Warnings on running local tests](https://github.com/PostHog/posthog/pull/1308) now don't appear.
* The experiments tab in the navigation didn't have a highlight. [Now it does](https://github.com/PostHog/posthog/pull/1298). That was weird.
* We [moved most of the analytics logic](https://github.com/PostHog/posthog/pull/1280) into a `queries` folder. This means it's in one place and in the future will make a ClickHouse integration way easier.

### 1.12.0 - Friday 29 July

- Shared Dashboards

![](https://posthog.com/static/65d34123d9987988980c13fba2713bf4/c83ae/shared-dashboard.png)

Dashboard on a TV in your office? Want to have a public stats page? Share a dashboard with someone who doesn't have a PostHog account? You can now publicly share a dashboard. Just click "Share Dashboard" and enable sharing. You'll get a link that's publicly accesible.

Changed your mind? You can always disable sharing.

- Aggregate Functions

![](https://posthog.com/static/118b6779d9282eb411849be82ce16676/44385/aggregate.png)

Want to know the average revenue per user? Want to know the lowest browser version anyone is using? You can now do Sum, Max, Min and Avg calculations on any event property and graph them in trends!

- Global Annotations

![](https://posthog.com/static/1d927d103ca02ecae58c602008c6eea7/776d3/annotations.png)

Digging through git commits to find out what changed to make the graphs go hay-wire? No more! You can now annotate when something happened (a big release, a bugfix or a launch) and make it super easy for your team-mates to figure out what's going on. Now global.

As part of this, you can now also manage, add and delete annotations from a central screen.

- Funnel Step Time 

![](https://posthog.com/static/3fb04aefb8a907937fed6b98d007bd4f/d52e5/funnel-step-time.png)

You can now see how long it takes users on average to get through steps in a funnel.

- Regex Filtering

![](https://posthog.com/static/9baa7627f8d3ad7e5149b43f8f5d2358/d54e4/regex.png)

Regex master? Put those skills to use on any property with regex filtering

- Retention Table Improvements

Previously the retention table was hardcoded to only recognize the `$pageview` event as a retention event. Now, you can select any action or event to measure retention on.

Clicking on any section in the retention table will tell you exactly what users fall in that item.


#### Bug Fixes and Performance Improvements

* We've added a button [to easily launch the toolbar](https://github.com/PostHog/posthog/pull/1186)
* We've made line charts more precise by [straightening the lines.](https://github.com/PostHog/posthog/pull/1238)
* We've enabled interval selection for sessions [too](https://github.com/PostHog/posthog/pull/1241)
* We're now using Typescript ([1](https://github.com/PostHog/posthog/pull/1297), [2](https://github.com/PostHog/posthog/pull/1286))
* We've [fixed various issues with annotations(https://github.com/PostHog/posthog/pull/1291)
* We don't refresh the Events table if you [don't select a property](https://github.com/PostHog/posthog/pull/1285)
* "All time" date filter [works on funnels again](https://github.com/PostHog/posthog/pull/1252)
* You can now [delete users from your team(https://github.com/PostHog/posthog/pull/1274)
* Fixed an issue where timestamps [were displayed incorrectly on sessions](https://github.com/PostHog/posthog/pull/1294)
* Fixed a bug where selecting "last 48 hours" [wouldn't return results](https://github.com/PostHog/posthog/pull/1264)
* Fixed issues with funnels loading [on dashboards](https://github.com/PostHog/posthog/pull/1266)
* [UUIDs are ugly](https://github.com/PostHog/posthog/pull/1255), so we just cut them off rather than wrapping entire lines in the events table
* [Samcaspus](https://github.com/samcaspus) contributed a little bit of magic: we now automatically adjust your date range if [you change the interval](https://github.com/PostHog/posthog/pull/1253)
* We added a button to dashboard that allows users to [easily add a new item(https://github.com/PostHog/posthog/pull/1242)
* enhanced ctrl + click new tab opening feature [](https://github.com/PostHog/posthog/pull/1248)
* Massively speed up [loading live actions](https://github.com/PostHog/posthog/pull/1182)
* Fix password validation and improve minimums notice (closes #1197) [](https://github.com/PostHog/posthog/pull/1204)
* Closes #1180 worker fails if timestamp is invalid [](https://github.com/PostHog/posthog/pull/1181)
* (abhijitghate)[https://github.com/abhijitghate] contributed an improvement to the way we display DAU's in the graph
* Fix an issue where [loading sessions would do an entire table scan](https://github.com/PostHog/posthog/pull/1221), and then throw it away
* [Automatically bind docker-compose 2to port 80](https://github.com/PostHog/posthog/pull/1257) for production deployments
* + a bunch of improvements to make local development better! ([1](https://github.com/PostHog/posthog/pull/1290), [2](https://github.com/PostHog/posthog/pull/1288), [3](https://github.com/PostHog/posthog/pull/1272), [4](https://github.com/PostHog/posthog/pull/1293))

### 1.11.0 - Friday 17 July

- Annotations

![](https://posthog.com/static/1d927d103ca02ecae58c602008c6eea7/c83ae/annotations.png)

- Cohort filters

![](https://posthog.com/static/9ad08691d6f6c70ae5168ba9fbedf2db/c83ae/cohort-filter.png)

- Retention table filtering

![](https://posthog.com/static/2a8f824019810bdb6b4459743eddffe0/c83ae/retention-filter.png)

- Many toolbar fixes.

![heatmap](../images/casts/heatmap.gif)

#### Bug fixes and performance improvements

* Some first-time contributors ran into errors with TemplateDoesNotExist, which [we've solved](https://github.com/PostHog/posthog/pull/1200)
* Add comprehensive Cypress tests for dashboards [to avoid bugs](https://github.com/PostHog/posthog/pull/1171)
* Add webpackbar for better [readability while developing](https://github.com/PostHog/posthog/pull/1185)
* Moves total to the bottom of the pie chart to fix z-index issues [readability while developing](https://github.com/PostHog/posthog/pull/1179)
* Fix an issue with [filtering on the event type](https://github.com/PostHog/posthog/pull/1168)
* Add Typescript to the [PostHog frontend codebase](https://github.com/PostHog/posthog/pull/1157)
* Fix the ability to [delete dashboards](https://github.com/PostHog/posthog/pull/1152)
* Add support [for LZ-String compression](https://github.com/PostHog/posthog/pull/1058)
* [Use Black for Python formatting](https://github.com/PostHog/posthog/pull/1136

### 1.10.1 - Thursday 2 July 2020

#### Bugfixes

- Actually include the version bump when you push a release! 🐛
- Add flutter docs and reorder flow [#1134](https://github.com/PostHog/posthog/pull/1134)
- Black all the things! [#1136](https://github.com/PostHog/posthog/pull/1136)

### 1.10.0 - Wednesday 1 July 2020

#### Toolbar

- It's like inspect element, but for user data.

![inspect](https://posthog.com/images/3ce1232ef29d0d59b4ac2779d8e97cf8/inspect.gif)

- Easily see the ranking of which parts of the page your users are interacting with the most:

![heatmap](https://posthog.com/images/782d9d2142c331403efdbec7ebd56145/heatmap.gif)

- We learned a ton about our product and website within minutes of trying this out.

![toolbar dance](https://posthog.com/images/55fe4bbc5e8fbc428fe4f1830f3d280c/dance.gif)

#### Feature flags

- Feature flags let you roll out changes to users with a certain property, or to a percentage of users, or some combo of the two.

![feature flags](https://posthog.com/static/2824e49b2d3200ba4260a1bb83edb6ad/db910/feature-flags.png)

#### Other exciting, enthralling and invigorating features

- Flutter Integration. You asked for it and now [it's here](https://posthog.com/docs/integrations/flutter-integration)!
- Retention page. PostHog already had stickiness, but now there is a table that demonstrates perhaps more clearly how your users are coming back (or not!)

![retention view](https://posthog.com/static/c72806fa990efb5ea9bcf852c9ba9ffe/dc333/retention-view.png)

- Better onboarding. We've had a go at redoing how our set up flow works, and will be tracking if it helps more people get through PostHog's own funnel!
- Platform.sh deployment. A very simple, new and trendy way to get up and running!
- Porter development. Join the cool kids and do  web development in the cloud. Thank you so much to [porter-dev](https://github.com/porter-dev) for creating this PR.
- Event name filtering. By popular demand, you can now filter the events table by the event name. Happy debugging your implementations!

![filter by event name](https://user-images.githubusercontent.com/1727427/84702990-c7f59f00-af57-11ea-8455-92fb89d9c9ae.png)

#### Bug fixes and performance improvements

* We are now more privacy friendly - you can [discard IP address data](https://github.com/PostHog/posthog/pull/1081)
* Added the offer of a [free pairing session](https://github.com/PostHog/posthog/pull/1028) to the contributing guide - ask us!!
* We fixed a bug with [the start times for the session view](https://github.com/PostHog/posthog/pull/1077)
* We [improved the ./bin/test command](https://github.com/PostHog/posthog/pull/1074)
* We now let you [break down users by their properties](https://github.com/PostHog/posthog/pull/1070) (it wasn't working before!)
* We [sped up the people page](https://github.com/PostHog/posthog/pull/1056) - pro tip: don't load stuff you don't need!
* We [disabled batching in the snippet](https://github.com/PostHog/posthog/pull/1049), since this helps prevent data loss
* Fixed a weird bug with [moving from sessions to trends](https://github.com/PostHog/posthog/pull/1039)
* Fixed [person properties being selected](https://github.com/PostHog/posthog/pull/1040), which was causing some issues with the stats.
* We now [automatically select hourly](https://github.com/PostHog/posthog/pull/1057) if you're looking at data from just today or yesterday - it was weird otherwise!
* We turned [today into the last 24 hours](https://github.com/PostHog/posthog/pull/1054) - you can now think of yourself as Jack Bauer
* The people modal now [has pagination](https://github.com/PostHog/posthog/pull/1042)
* We [now copy array.js.map](https://github.com/PostHog/posthog/pull/1047) as well as everything else to better debug errors
* We now [show a warning for old browsers](https://github.com/PostHog/posthog/pull/1046), and feel bad for those in big enterprises that must use them!
* [Black now added](https://github.com/PostHog/posthog/pull/1043) to post commit hooks, so we don't get crazy all-file reformatting
* Fixed an issue with [force refreshes for cache](https://github.com/PostHog/posthog/pull/1035) in certain places
* We [fixed a failing test problem](https://github.com/PostHog/posthog/pull/1036) with team_id
* Improved [person properties and pagination](https://github.com/PostHog/posthog/pull/976)
* Solved [a Sentry error](https://github.com/PostHog/posthog/pull/1029) with overly long text
* We [cleaned the configs for release-drafter](https://github.com/PostHog/posthog/pull/1088)


### 1.9.0 - Thursday 18 June 2020

- [Sessions view](https://github.com/PostHog/posthog/pull/926)
![sessions overview](https://posthog.com/static/b64e1508790f6b60958d5d320f2b8a22/efc66/sessions-overview.png)
- You can then see exactly how a user interacted with your app:
![sessions more detail](https://posthog.com/static/c4fe51ff11bbe87eb64c00daf7cc3d78/efc66/session-broken-out.png)
This should really help with debugging, or just trying to get a detailed view of what users are up to.

#### Better testing

* [Fixed Cypress tests](https://github.com/PostHog/posthog/pull/1015)
* Enabled [running cypress in parallel](https://github.com/PostHog/posthog/pull/959), which saved a minute.
* [Fixed cypress linting errors and sped up tests further](https://github.com/PostHog/posthog/pull/865)
* [Cached PostHog's yarn builds](https://github.com/PostHog/posthog/pull/927), which took e2e tests down by around 30%.
* Finally, we now [wait for PostHog to start serving requests](https://github.com/PostHog/posthog/pull/920) rather than the 60 second sleep when running Cypress.

[Develop PostHog with Porter](https://posthog.com/docs/developing-locally#using-porter)

[Management command for millions of events](https://github.com/PostHog/posthog/pull/475)

[Set properties to anonymous users](https://github.com/PostHog/posthog-js/pull/43)

#### Bug fixes and performance improvements
* We worked hard on improving caching to speed things up. We [fixed cache refreshing](https://github.com/PostHog/posthog/pull/1035) in a few areas, we made a few [caching adjustments](https://github.com/PostHog/posthog/pull/1023) to fix #1022. Finally, we now use [redis to cache results](https://github.com/PostHog/posthog/pull/972).
* Save time! You can now [create actions from the trends page](https://github.com/PostHog/posthog/pull/990).
* [Upgrade to posthog-js 1.2.0 to support dynamic params](https://github.com/PostHog/posthog/pull/957).
* We fixed long href inserts - the href [can now go up to 2048 characters](https://github.com/PostHog/posthog/pull/1027) before truncation. Someone must have had some funky urls going on...
* [We prevented intermittent issues with yarn build](https://github.com/PostHog/posthog/pull/1026)
* We [fixed a bug](https://github.com/PostHog/posthog/pull/1021) that caused cohorts to fail when actions were deleted
* We [solved a problem](https://github.com/PostHog/posthog/pull/980) with comparing trend sessions distribution
* We [added a limit to number of returned entities for breakdowns](https://github.com/PostHog/posthog/pull/1008) so queries don't time out
* We [created a fix](https://github.com/PostHog/posthog/pull/1013) for an issue with heartbeats
* We [made it clearer](https://github.com/PostHog/posthog/pull/1014) that PostHog SaaS users are on the latest version
* We [slashed CPU consumption for VSCode](https://github.com/PostHog/posthog/pull/1007) by excluding a folder
* Generated a [performance improvement for element stats](https://github.com/PostHog/posthog/pull/991)
* We [stopped giving way too many decimal points](https://github.com/PostHog/posthog/pull/984) on our graphs!
* Trends page [UX improvement](https://github.com/PostHog/posthog/pull/919)
* [Improved filtering](https://github.com/PostHog/posthog/pull/986) on elements
* We fixed [a race condition](https://github.com/PostHog/posthog/pull/973/commits/953af2326dff94e8ae1d75cd6ea0fc2c64567857)
* [We don't rely](https://github.com/PostHog/posthog/pull/949) on \$ to separate PostHog's events
* We [removed the redundant math selector](https://github.com/PostHog/posthog/pull/950) on funnels - it didn't do anything!
* [Django upgraded to 3.0.7](https://github.com/PostHog/posthog/pull/932)
* We [made HTTPS work locally](https://github.com/PostHog/posthog/pull/910) - we had lots of community issues raised, so that should make it easier to get started with!
* We [improved the setup overlay layout](https://github.com/PostHog/posthog/pull/904)
* We [sped up the events endpoint](https://github.com/PostHog/posthog/pull/903) by just hitting the current week's partitions
* We solved a problem [with temporary tokens](https://github.com/PostHog/posthog/pull/909)
* We added [webpack HMR](https://github.com/PostHog/posthog/pull/878) and hashes to chunk filenames. (#878)


### 1.8.0 - Wednesday 3 June 2020

- [Cumulative graphs](https://github.com/PostHog/posthog/pull/862)

![cumulative graphs](https://posthog.com/images/8b9a5516ddcc2ac7030b690273ed7e8e/cumulative-graph.gif)

- [More powerful paths](https://github.com/PostHog/posthog/pull/897)

![Paths start point](https://posthog.com/static/07bcede22293f441670c690377152f77/49898/paths-start-point.jpg)

![Paths filtering by properties](https://posthog.com/static/2738ad9eea88ccc59e09a22d5f65d80d/86f7d/paths-filtering.jpg)

- [Add property filters to actions + lots of improvements (#841)](https://github.com/PostHog/posthog/pull/841)

![Actions property filter](https://posthog.com/static/f4099601731f26a7d1f98a2b8fa9378d/fbd2c/actions-property-filter.jpg)

* We cleaned up descriptions in the [breakdown filter](https://github.com/PostHog/posthog/pull/886).
* The [UX is nicer](https://github.com/PostHog/posthog/pull/863) for selection a URL on creating an action.
* We made it simpler to understand [how to use custom events](https://github.com/PostHog/posthog/pull/873) during the setup process.
* The token issues, oh the token issues. [Fixed](https://github.com/PostHog/posthog/pull/909) and [fixed](https://github.com/PostHog/posthog/pull/894).
* It was time for our events table [to become Ant Designed](https://github.com/PostHog/posthog/pull/895).
* Pre-2020 events [won't affect partitions](https://github.com/PostHog/posthog/pull/875) any more.
* [Better debugging](https://github.com/PostHog/posthog/pull/854) with Sentry.
* Scrollbar [small issue be gone](https://github.com/PostHog/posthog/pull/900).
* We [improved](https://github.com/PostHog/posthog/pull/885) how empty funnels work.
* Events are [40ms faster to process](https://github.com/PostHog/posthog/pull/833) - 25% quicker!
* The sidebar [works properly on mobile](https://github.com/PostHog/posthog/pull/839) - no more squished interface on your cell phone.
* Fix a bug with [selecting filters](https://github.com/PostHog/posthog/pull/844)
* [Funnels are simpler](https://github.com/PostHog/posthog/pull/881).
* [Solved](https://github.com/PostHog/posthog/pull/874) a tricky bug on app.posthog.com caused by URLs with non-utf8 or raw binary query parameters.
* Nothing to do with [dubious cheese](https://www.babybel.com/welcome), we [fixed errors with babel](https://github.com/PostHog/posthog/pull/861)
* [Improved toolbar UX](https://github.com/PostHog/posthog/pull/890) for actions to fix a small [issue](https://github.com/PostHog/posthog/issues/889). 
* PostHog will now [cache SQL and parameters between events processing](https://github.com/PostHog/posthog/pull/845). This speeds things up by a further 40%.
* We [refactored more classes to hooks](https://github.com/PostHog/posthog/pull/898), fixing a bug with event name labels along the way.

### 1.7.0 - Wednesday 27 May 2020

- [Reactive Native](https://github.com/PostHog/posthog-react-native)
- [Comparison charts](https://github.com/PostHog/posthog/pull/824)

![Comparison charts](https://posthog.com/images/a1571726df68831e4626a937a19821d0/side-by-side-comparison.gif)


- [Tooltip: View the users inside each datapoint](https://github.com/PostHog/posthog/pull/830/commits/64e1ef34b5d8565934b1980d33432cef4e7002f7)

![Hover breakdown](https://posthog.com/static/729a492575e82595e30266d63dc13765/c83ae/hover-breakdown.png)

- [Property keys explained](https://github.com/PostHog/posthog/pull/822)

![property keys with explanations](https://user-images.githubusercontent.com/1727427/82579579-ed280500-9b85-11ea-92fe-6e7fe67c9d86.png)

- [Automatic domain detection](https://github.com/PostHog/posthog/pull/815)

![automatic domain detection](https://user-images.githubusercontent.com/1727427/82486899-72071600-9ad5-11ea-8bd1-2f589cc69d34.png)

* Developing PostHog is now a bit less tedious. We [halved the time](https://github.com/PostHog/posthog/pull/826) it takes to install python dependencies for any deployment.
* We've written [a lot of front end tests](https://github.com/PostHog/posthog/pull/802), as well as a [regression test](https://github.com/PostHog/posthog/pull/819) for single step funnels, where there was a bug - [now fixed](https://github.com/PostHog/posthog/pull/817).
* We neatened dashboard items so they're [closer together](https://github.com/PostHog/posthog/pull/846) in the navigation.
* We [improved our Sentry setup](https://github.com/PostHog/posthog/pull/842).
* Marius [fixed the way tables display](https://github.com/PostHog/posthog/pull/838) when they're on a dashboard.
* Eric [slayed a bug](https://github.com/PostHog/posthog/pull/832) when the People page wouldn't load with entity specific filters applied.
* We've had several users with very high scale pushing the limits of redis. We have more work to do here, but we've [improved the way we handle filled up servers](https://github.com/PostHog/posthog/pull/825).
* A little [header spring cleaning](https://github.com/PostHog/posthog/pull/831).
* We [fixed a bug](https://github.com/PostHog/posthog/pull/835) with suggestions loading, and another with [EditAppUrls null check](https://github.com/PostHog/posthog/pull/829).
* Cohort property filters had a small issue, [now fixed](https://github.com/PostHog/posthog/pull/828).
* AntD's gradual takeover of our app and website continued - it was [added to more dropdowns](https://github.com/PostHog/posthog/pull/814) this week.
* We prevented requests to update server for those who have opted out, and [added fine grained control](https://github.com/PostHog/posthog/pull/821) to the opt out flow.

### 1.6.0 - Wednesday 20 May 2020

- [Dashboard presentation mode](https://github.com/PostHog/posthog/pull/753)

![](https://posthog.com/static/6c585ad804ad3855cf916b530a99e9d0/05ed2/presentation-mode.png)

- [Dashboard resizing](https://github.com/PostHog/posthog/pull/746)

![](https://posthog.com/images/a73d77c1d5e05f0a5337acc967b178ce/dashboards-moving.gif)

- [Paths works with events](https://github.com/PostHog/posthog/pull/692)

![](https://posthog.com/images/91e2b9a8274bfba62fda39dc31cf0fb7/paths-with-events.gif)

- [Dashboard mobile support](https://github.com/PostHog/posthog/pull/775)
- [Microsoft Teams support](https://posthog.com/docs/integrations/microsoft-teams)
- [You can now use](https://github.com/PostHog/posthog/pull/768) the django-debug-toolbar to diagnoze performance issues better
- We added [ES Lint](https://eslint.org/), for JavaScript linting.
- We fixed [property filter array issue](https://github.com/PostHog/posthog/pull/769)
- [Optimize funnel rendering](https://github.com/PostHog/posthog/pull/792) is a major improvement in speed for those with many events - now 1 order of magnitude faster. 
- [Multiple filters with same key](https://github.com/PostHog/posthog/pull/738), fixed a bug that means you can now have multiple filters that are the same ie $current_url doesn't equal A and $current_url doesn't equal B
- [Event partioning](https://github.com/PostHog/posthog/pull/733), which speeds up trends and paths pages in particular. Learn more about [scaling PostHog](/docs/scaling-posthog).
- The component Deletewithundo wasn't working because of property mixup, [now it is](https://github.com/PostHog/posthog/pull/750)!
- [Funnels](https://github.com/PostHog/posthog/pull/751) and [Actions](https://github.com/PostHog/posthog/pull/757) now use Ant Design
- We temporarily [removed stickiness breakdowns](https://github.com/PostHog/posthog/pull/774), as they were causing issues.
- [Better handling of breakdown views](https://github.com/PostHog/posthog/pull/758) when users don't have the property.
- [Fixed an issue](https://github.com/PostHog/posthog/pull/725) with viewing certain queries over all time.
- [Resolved an issue](https://github.com/PostHog/posthog/pull/748) with sessions where null conditions were missing
- Fixed the [cohort input search](https://github.com/PostHog/posthog/pull/785) bug
- Solved [a bug with navigating to users](https://github.com/PostHog/posthog/issues/794)
- [Improved our event insertion scalability](https://github.com/PostHog/posthog/pull/797)

### 1.5.0 - Wednesday 13 May 2020

- [Multiple dashboards](https://github.com/PostHog/posthog/pull/740)
![](https://posthog.com/changelog/multiple-dashboards.png)
- [Dark-er mode](https://github.com/PostHog/posthog/pull/740)
![](https://posthog.com/changelog/dark-sidebar.png)
- [Break down by cohort](https://github.com/PostHog/posthog/pull/690)
![](https://posthog.com/changelog/breakdown-cohort.png)


- [Big refactor of how we do routing in the app](https://github.com/PostHog/posthog/pull/717) which means going backwards and forwards should work a lot smoother
- [Faster loading of paths](https://github.com/PostHog/posthog/pull/729)
- [More accurate DAU/uniques count](https://github.com/PostHog/posthog/pull/734)
- [Fix dotted line appearing on completed days](https://github.com/PostHog/posthog/pull/735). Thanks [Jujhar](https://github.com/Jujhar)!

### 1.4.0 - Wednesday 6 May 2020

- Added filtering of properties individually. For both trends and funnels, you can now add filters for each event/action individually
![events](https://posthog.com/wp-content/uploads/2020/05/captured.gif)

- Added Breakdown by properties in graph.
![graph](https://posthog.com/wp-content/uploads/2020/05/captured-1.gif)

- Session time series, you can now see how time spend in your app changes over time
![session time series](https://posthog.com/wp-content/uploads/2020/05/Screenshot-2020-05-06-at-10.59.34.png)

- Export cohorts as CSV
![export cohorts](https://posthog.com/wp-content/uploads/2020/05/Screenshot-2020-05-06-at-10.53.26.png)

- Edit frontend selector for actions in PostHog
![frontend selector](https://posthog.com/wp-content/uploads/2020/05/Screenshot-2020-05-06-at-10.56.03.png)

- Setup page redesign
![setup page redesign](https://posthog.com/wp-content/uploads/2020/05/Screenshot-2020-05-06-at-11.13.06.png)

- Restrict access to instance by IP address (#679, #682)
- Fix today + hourly filtering not working (#700)
- Fix timestamps if users had wrong dates set locally (#693, #697, #699)
- Add $screen to events table (#681)
- Add noindex to login/signup screens (#702)
- Speed up cohorts page and use antd (#706)

### 1.3.0 - Wednesday 29 April 2020

- We have added an Android library so you can now capture events in your Android app and send them to PostHog, we can automatically capture screen changes, and send any other events that you like

![android events](https://posthog.com/wp-content/uploads/2020/04/android-events.gif)

- There is now, also a [PostHog Gatsby plugin](https://posthog.com/docs/integrations/gatsby-integration)

- We have added URL wildcards so you can use % as a wildcard when setting up an action

![url wildcards](https://posthog.com/wp-content/uploads/2020/04/Posthog-19-e1588157571429.png)

- We have also updated the Trends page design as well as adding trends info hints. Trends is the default homepage when logging into PostHog.

![trend layout](https://posthog.com/wp-content/uploads/2020/04/Posthog-21-e1588171341976.png)

![trend hints](https://posthog.com/wp-content/uploads/2020/04/Fullscreen_4_29_20__12_09_PM-e1588158606164.png)

- The Events table can now be sorted by timestamp.

![timestamp reverse](https://posthog.com/wp-content/uploads/2020/04/timestampreverse.gif)

- Added a more strict flake8 setup and improvements
- Upgraded Kea to `2.0.0-beta.5`
- Implemented AntD into Setup page
- You can now allow access to your PostHog instance by IP address for more security. this does not apply to the JS snippet or the event capture API
- Added model for typing of filters
- Added copy code to clipboard changes
- Use forward for header in middleware if applicable
- Move get_ip_address to utils
- Fixed redirect to be explicit for /Trends
- Moved models to separate files
- Added link to docs for local deployment
- Warn instead of crash on invalid selector when using the front-end toolbar


#### Bug Fixes
- Fixed issue with default trends route
- Fixed Setup page operations not working
- Fixed crash when hovering over events
- Fixed issues with $create_alias when users have multiple distinct_ids attached to them
- Fixed trends save to dashboard issue
- Fixed adding dashboarditem with set dates


### 1.2.0 - Wednesday 22 Aptil 2020

- We have added an iOS library so you can now capture events in your iOS app and send them to PostHog, we can automatically capture screen changes, and send any other events that you like

Click [here](https://posthog.com/docs/integrations/ios-integration) for instructions on how to install it on your app.

- We have added Sessions to /trends with two modes: “Average session length”, which shows you how long sessions are and how many, and “distribution” which makes it super easy to spot whether sessions are uniformly distributed or whether there are outliers

![sessions gif](https://posthog.com/wp-content/uploads/2020/04/Sessions.gif)

- Funnels can be filtered by properties 

![Funnel properties](https://posthog.com/wp-content/uploads/2020/04/funnel-properties.gif)

- Added indexes so loading /trends is super fast, even with millions of events
- We have offloaded storing events to workers, so that calls to our events API are non-blocking, and you can scale insertion of events independently from the rest of PostHog
- Removed drf-yasg in favor of our own hosted docs
- Added layout/header components of Ant design
- Updated property filters to be "tokenized"
- Updated the way we display actions/events in trend graphs if those action/events have no data in a given timeframe
- Updated property filters so that they 'AND' rather than 'OR' if you filter multiples

#### Bug Fixes
- Fixed unable to sign up to teams
- Fixed stickniess not loading 
- Fixed property filter bug that would break when multiples were applied in some circumstances
- Fixed setting event name in action
- Fixzed event filtering with teams


### 1.1.0.1 - Thursday 16 April 2020

- Fix issues with custom events while creating actions

### 1.1.0 - Wednesday 15 April 2020

Important! We've added Celery workers. We'll move tasks to workers to speed up a lot of actions in PostHog. [See update instructions](https://posthog.com/docs/deployment/upgrading-posthog#upgrading-from-before-1011) on how to enable workers.

- Users can integrate PostHog with Slack to send push notifications when events are triggered

![Slack action](https://posthog.com/wp-content/uploads/2020/04/Slack-action.gif)

- Funnels can now be filtered by Events not just Actions
- Funnels can be filtered by time intervals as well

![funnel intervals](https://posthog.com/wp-content/uploads/2020/04/funnels-by-time.gif)
![funnel with events](https://posthog.com/wp-content/uploads/2020/04/funnel-with-events.gif)

- Added Ant Design to PostHog

![ant design sidebar](https://posthog.com/wp-content/uploads/2020/04/Posthog-6-e1586882580994.png)
![ant design buttons](https://posthog.com/wp-content/uploads/2020/04/Posthog-10.png)

- Trends can now be filtered by different time intervals

![time intervals](https://posthog.com/wp-content/uploads/2020/04/time-intervals.gif)

- Added dotted lines to represent data yet to be determined

![Dotted line example](https://posthog.com/wp-content/uploads/2020/04/dotted-lines.png)

- Trends graphs have fixed the X axis at 0 

![x axis 0](https://posthog.com/wp-content/uploads/2020/04/Posthog-7.png)

- Daily Active Users (DAUs) added as a default dashboard

![DAU dahsboard](https://posthog.com/wp-content/uploads/2020/04/Posthog-8.png)

- Changed the way we rendered urls in Paths to reflect better on different screen sizes

![paths](https://posthog.com/wp-content/uploads/2020/04/Posthog-9.png)

- Updated UX when saving actions to be clearer

![actions save](https://posthog.com/wp-content/uploads/2020/04/save-actions-ux.gif)

- Changed the way we store events properties, we now store all event names and property names against the Team
- Refactored PropertyFilters into a function
- Added filter by event name to event properties
- Added mypy rules
- Using dateutil for datetime
- Added timestamp index to allow event tables to load at large volumes
- Updated helm charts to work with redis and workers
- Added a Babel plugin to reduce antd module load
- We now use offset instead of timestamp of posthog-js to avoid the wrong user time - previously if your local machine had a time set different to your location (or if the time was just off) we would have displayed that time.
- Using npm instead of yarn in copy command as Heroku doesn't have yarn
- We now use posthog-js to get array.js
- Removed unused indexes from migrations
- Updated PostHog snippet

#### Bug Fixes
- Removed unused future import to prevent Heroku deployments breaking
- Fixed dupliucated users in Cohorts
- Type Migration to prevent /trend bug when navigating to a url from a dashboard
- Added missing type in initial dahsboard element creattion to fix the same bug as above
- Fixed collectstatic on fresh Heroku updates
- Fixed network timeout yarn for antd
- Fixed npm command to copy array.js
- Fixed date filter not detecting moment
- Fixed redis error when upgrading Heroku
- Stopped throwing an error if a user doesn't have a distinct id
- Fixed a trends people bug that ignored the time interval selected
- Fixed site_url pass to slack from request


### 1.0.11 - Wednesday 8 April 2020

Important! We've added Celery workers. We'll move tasks to workers to speed up a lot of actions in PostHog. [See update instructions](https://posthog.com/docs/deployment/upgrading-posthog#upgrading-from-before-1011) on how to enable workers.

- Users can filter the trends view by any event rather than just actions

![events in trends](https://posthog.com/wp-content/uploads/2020/04/events-in-trends.gif)

- Users can now change password in /setup

![password change](https://posthog.com/wp-content/uploads/2020/04/Posthog-3.png)

- Users can also reset password at login screen
- Added a logout button

![logout button](https://posthog.com/wp-content/uploads/2020/04/logoutbuton.gif)

- Added GitHub / GitLab Social Authorization

![social auth](https://posthog.com/wp-content/uploads/2020/04/Posthog-1.png)

- Added Stickiness explanation in /trends > Shown As > Stickiness

![Stickiness explanation](https://posthog.com/wp-content/uploads/2020/04/Posthog-4.png)

- Precalculated events that matched actions, this massively speeds up anything that uses actions
- Added Celery background workers
- Added gunicorn workers in docker-server script
- Added email opt in for PostHog Security and Feature updates
- Removed yarn cache in production image
- Cleaned docker yarcn cache
- Reduced size of Docker images by ~80MB
- Set default password for postgres in docker-compose.yml
- Sped up the event insert by only loading actions that were really necessary
- Migrated ip field to event property
- Updated all links to point to new docs domain
- Added GitLab API url
- Added Async JS snippet
- Docker and server updates for helm

#### Bug Fixes
- Fixed some instances of Cohort page hangs
- Fixed demo actions not being recalculated
- Fixed breakdown error on DAUs where tables could not be filtered
- Fixed array.js
- Fixied ActionStep.url_ so that it can be null


### 1.0.10.2 - Friday 3 April 2020

- Precalculate Actions to speed up everything (dashboards/actions overview etcetera)
- Fix error running Docker file

### 1.0.10.1 - Wednesday 1 April 2020

- Fixes for Helm charts

### 1.0.10 - Wednesday 1 April 2020

- Users can now be identified directly from Trend Graphs

![users in trend graph](https://posthog.com/wp-content/uploads/2020/03/usersintrends.gif)

- Added demo data to new instances of /demo

![demo data copy](https://posthog.com/wp-content/uploads/2020/03/HogFlix.png)

- Built a Helm Chart for PostHog 

- Ordering is now by timestamp instead of id

- Fixed typing errors

- Fixed funnels not working if order was set incorrectly

- Avoided team leakage of person properties

- Fixed live actions error that resulted in opening multiple events

### 1.0.9 - Wednesday 25 March 2020

- Stickiness now shown on Trend Graph

![stickiness](https://posthog.com/wp-content/uploads/2020/03/stickiness-gif.gif)

- Funnel builder changes

![funnel builder](https://posthog.com/wp-content/uploads/2020/03/newfunnel.gif)

- Changed 'Add event property filter' to 'Filter events by property'.

- Added drop down to all filters for event properties

![filters](https://posthog.com/wp-content/uploads/2020/03/Posthog-23.png)

- Added '_isnot' and 'does not contain' to properties filters

![doesnotcontain](https://posthog.com/wp-content/uploads/2020/03/isnotdoesnotcontain.gif)

- Moved API key to it's own box

- Various performance updates

- Bug fixes


### 1.0.8.2 - Wednesday 18 March 2020

- Fixes bug where events wouldn't be filtered under /person or /action.

### 1.0.8 - Wednesday 18 March 2020

- Moved actions into /event submenu

![moved action](https://posthog.com/wp-content/uploads/2020/03/Posthog-3.png)

- Improved Actions Creation

![improved actions creation](https://posthog.com/wp-content/uploads/2020/03/newtoolbar.gif)

- Delete user data

![delete user data](https://posthog.com/wp-content/uploads/2020/03/Posthog-4.png)

- Various performance improvements

- Bug fixes

- Turbolinks: Support for navigating between pages with the toolbar open

### 1.0.7 - Wednesday 10 March 2020

- Added changelog and reminder to update to app.
- Filtering action trends graphs

![filtering action trends gif](https://posthog.com/wp-content/uploads/2020/03/Action-trend-filter-gif.gif)
- Exact/contains matching for URLs in actions

![exact/contains matching gif](https://posthog.com/wp-content/uploads/2020/03/image-2.png)
- Filtering paths by date

![Filtering paths by date](https://posthog.com/wp-content/uploads/2020/03/Path-by-date-gif.gif)
- Graphs show numbers

![graph show numbers](https://posthog.com/wp-content/uploads/2020/03/image-1.png)
- Allow multiple URLS when creating actions

![multiple urls when creating actions](https://user-images.githubusercontent.com/53387/76166375-54751200-615e-11ea-889f-d0ec93356cf2.gif)
- Better property filters

![image](https://user-images.githubusercontent.com/1727427/76364411-5831a180-62e2-11ea-81f1-f0c1832b7927.png)

- **API change** If you're using the trends api, filtering by action ID is deprecated in favour of `api/action/trends?action=[{"id":1}]`
