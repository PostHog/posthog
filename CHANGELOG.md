# Changelog

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
