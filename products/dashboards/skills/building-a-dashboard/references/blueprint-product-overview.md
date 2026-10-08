# Blueprint: product overview

**Question:** Is the product growing, and do new users become regular users?

Use for "product health", "KPI dashboard", "key metrics", "overview", "main dashboard", "weekly metrics", or a founder, exec, or PM pulse.
Use it too when the user names a growth framework such as AARRR: keep the tiles and rules below and name the sections after the framework's stages.
Do not use it for one feature or one flow. Those requests have no blueprint yet, so build them with the rest of the skill.

Read [design-guidelines.md](./design-guidelines.md) first. This file says which tiles to build.

## Settle the definitions before you build

Three definitions decide every number on this dashboard. A guessed definition of "activated" can move the activation rate from under 10% to over 50% on the same data, so do not guess these.

- **Active.** The core action: what a person does when they get value from the product. A pageview or an app open is not a core action.
- **Signed up.** The event that marks a new account.
- **Activated.** A new user who made the product a habit: they got value in several of their first weeks, for example the core action in at least 3 of the 4 weeks after signup. One first action is a setup step, not activation.
- **Paid,** only if the product charges: the event that marks a first payment, not a plan selection or a card on file.

### Reuse a definition the team already has

Most projects have defined these somewhere already. Look in this order, and skip a source whose tool you do not have:

1. **What the user said** in the request.
2. **Saved metrics.** An approved Data Catalog metric for active users, signups, activation, or paying customers (`posthog:metric-list`, then `posthog:metric-describe`). Use its events and filters in your tiles.
3. **Saved insights and actions.** Search `system.insights` and `system.actions` with `posthog:execute-sql` for names such as "signup", "activation", "activated", "active users", "WAU", or "retention". Open the best match with `posthog:insight-get` and copy its definition: the events, the filters, and the time window.
4. **Project configuration.** `posthog:project-get` returns the signup, activity, and payment events when the team has set them. Check that each one still receives events.
5. **The events list** from `posthog:read-data-schema`, when nothing above exists.

A project often has more than one definition, for example an activation rate for each team or product. When you find several, prefer them in this order:

- One that the person asking created or last edited. `posthog:user-get` gives their ID. Compare it with `created_by_id` and `last_modified_by_id`.
- One that belongs to the product area the request is about. Judge by its name, its description, and the dashboard it sits on.
- The one edited most recently.

If two candidates still count different things and you cannot tell which the user means, ask. Name each candidate and say what it counts.

The core action can be an action that combines several events. Lifecycle, stickiness, and retention accept one event or one action, so a product with several core events needs an action. If none exists, use the single most representative event for those three tiles and say so.

### When the project does not answer

Ask the user before you build, in one message, and only about what you could not find: which event marks a signup, what counts as active, what counts as activated, and whether to count people or accounts.
If you cannot ask, choose, and put your choices first in your summary and in the dashboard description.

Run the heaviest queries once before you build on them, usually the funnel and the active-users trend. If one times out or runs out of memory, do not retry it unchanged: shorten the range or use a lighter event.

**Count one thing.** Choose people or accounts for the whole dashboard, and count that unit in every tile. For a B2B product (`posthog:project-get` shows the business model and the account group), count accounts.

## Interval

Use a weekly interval unless people use the product most days and the user asks for a daily view.

| Interval        | Dashboard `filters` | The headline row shows |
| --------------- | ------------------- | ---------------------- |
| Weekly (`week`) | `date_from: "-90d"` | The last complete week |
| Daily (`day`)   | `date_from: "-30d"` | Yesterday              |

Every insight hides the period in progress, as the design guidelines describe, so the last point is always a complete week or day.

## Layout

Box is `w` x `h` on the 12-column grid. Rows follow the order of the table.

| Section    | Tile                    | Insight                                                                     | Needs                     | Box    |
| ---------- | ----------------------- | --------------------------------------------------------------------------- | ------------------------- | ------ |
| Headline   | Active users            | Trends, core action, unique count per interval, Metric with `latest`        | Core action               | 3 x 3  |
| Headline   | New signups             | Trends, signup event, unique count per interval, Metric with `latest`       | Signup event              | 3 x 3  |
| Headline   | Core actions            | Trends, core action, `total` per interval, Metric with `latest`             | Core action               | 3 x 3  |
| Headline   | New paying customers    | Trends, paid event, unique count per interval, Metric with `latest`         | Paid event                | 3 x 3  |
| Growth     | Active users            | Trends, core action, unique count per interval, line                        | Core action               | 6 x 5  |
| Growth     | New signups             | Trends, signup event, unique count per interval, line                       | Signup event              | 6 x 5  |
| Growth     | New, returning, dormant | Lifecycle on the core action                                                | Core action               | 12 x 5 |
| Activation | Signup to first use     | Funnel, steps: signup, 0-2 steps between, first core action                 | Signup event, core action | 6 x 5  |
| Activation | Activation rate         | The share of each signup week that met the activation definition            | Activation definition     | 6 x 5  |
| Engagement | What people do          | Trends, 5-8 main actions as series, unique count, `ActionsBarValue`         | Core action               | 6 x 5  |
| Engagement | Intervals active        | Stickiness on the core action, at the dashboard's interval                  | Core action               | 6 x 5  |
| Retention  | Signup cohort retention | Retention: start event signup, return event core action, first-time, weekly | Signup event, core action | 12 x 5 |

"Unique count" means unique users (`math: "dau"`) when the dashboard counts people, and unique accounts (`math: "unique_group"` with the group type index) when it counts accounts.
For accounts, also aggregate the funnel, lifecycle, and retention tiles by the account group.
The headline signup number must equal the funnel's first step for the same interval.

Name the "Core actions" tile after what it counts, such as "Reports created".
Headline tile names are about 20 characters at most. A longer name is cut off at three columns wide.

**The headline row holds counts, not rates.** Activation, conversion, and retention rates belong to a cohort: the people who signed up in a period and what they did later. A trends formula cannot follow a cohort. It divides this week's activations by this week's signups, which can read twice the true rate.

**Activation rate.** When the team already has an activation insight, add that insight to the dashboard as it is.
Otherwise build it from the definition. A habit definition, such as the core action in 3 of the first 4 weeks, cannot be a funnel. Build a SQL insight that shows, for each signup week, the share of new users who met it, and leave out signup weeks whose window is still open. Show it as a line chart, not a table.

For "What people do", choose the actions from the core action's own events or from the most-used custom events, one per product area. Leave out pageviews, autocapture, and system events.

### When something is missing

The table is a starting shape, not a fixed grid. Build only the tiles whose "Needs" you have, then close the gaps:

- Headline row: three tiles are `4 x 3` each, and two are `6 x 3`.
- A pair with one tile left: make that tile full width, `12 x 5`.
- A section with no tiles left: leave out its heading too.

Tell the user what is missing and which event or definition would fill it.

## Adapt

- **Daily.** Use the daily row of the interval table. Leave out the lifecycle and retention tiles. They need whole weeks, and a 30-day range holds too few of them.
- **Revenue.** If a paid event exists and the user asked about money or runs the business, add a "Revenue" section: new paying customers per interval, and a signup-to-paid funnel with a window long enough for the sale.
  Revenue amounts need a numeric property or a warehouse source. Never estimate an amount from event counts.
- **A named framework.** For AARRR and similar, name the sections after the stages and keep the headline row as it is. A stage the project has no clean event for (often referral) gets no section. Say so in your summary instead of relabeling something else.
- **Mobile.** Add one chart of active users by platform or app version. Do not add the breakdown to the main chart.
- **Early product.** With fewer than about 100 active users per interval, show counts and say the sample is small.
- **A set.** If the user wants depth on activation, retention, or revenue, keep this dashboard as the overview and build one more dashboard per area.

## Avoid

- A table as a tile.
- An estimated rate in the headline row.
- Pageviews or sessions as the measure of an active user.
- A first action counted as activation.
- Cumulative totals in the headline row. They only go up and hide a decline.
- People in one tile and accounts in the next.
- A SQL copy of a governed metric as a tile, when a native insight can use the metric's events and filters.
- Retention defined as "any event". Use the core action as the return event.

## Tell the user

End with a short summary that leads with the definitions you used for active, signed up, and activated, and where each came from.
Then list any tile that is empty or missing and why, and anything you want the user to confirm.
