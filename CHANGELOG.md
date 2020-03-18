# Changelog

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
