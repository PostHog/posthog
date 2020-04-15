# Changelog

### 1.1.0 - Wednesday 15 April 2020

Important! We've added Celery workers. We'll move tasks to workers to speed up a lot of actions in PostHog. [See update instructions](https://docs.posthog.com/#/upgrading-posthog?id=upgrading-from-before-1011) on how to enable workers.

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

Important! We've added Celery workers. We'll move tasks to workers to speed up a lot of actions in PostHog. [See update instructions](https://docs.posthog.com/#/upgrading-posthog?id=upgrading-from-before-1011) on how to enable workers.

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
