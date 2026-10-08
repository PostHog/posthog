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
- **Activated.** The first milestone that shows a new signup got value. It must be something a real share of signups do not reach.
- **Paid,** only if the product charges: the event that marks a first payment, not a plan selection or a card on file.

### Reuse a definition the team already has

Most projects have defined these somewhere already. Look in this order, and skip a source whose tool you do not have:

1. **What the user said** in the request.
2. **Saved metrics.** An approved Data Catalog metric for active users, activation, or paying customers (`posthog:metric-list`, then `posthog:metric-describe`). Use its events and filters in your tiles.
3. **Saved insights and actions.** Search `system.insights` and `system.actions` with `posthog:execute-sql` for names such as "activation", "activated", "active users", "WAU", or "retention". Open the best match with `posthog:insight-get` and copy its definition: the events, the filters, and the conversion window.
4. **Project configuration.** `posthog:project-get` returns the signup, activity, and payment events when the team has set them. Check that each one still receives events.
5. **The events list** from `posthog:read-data-schema`, when nothing above exists.

A project often has more than one definition, for example an activation rate for each team or product. When you find several, prefer them in this order:

- One that the person asking created or last edited. `posthog:user-get` gives their ID. Compare it with `created_by_id` and `last_modified_by_id`.
- One that belongs to the product area the request is about. Judge by its name, its description, and the dashboard it sits on.
- The one edited most recently.

If two candidates still count different things and you cannot tell which the user means, ask. Name each candidate and say what it counts.

The core action can be an action that combines several events. Lifecycle, stickiness, and retention accept one event or one action, so a product with several core events needs an action. If none exists, use the single most representative event for those three tiles and say so.

### Check a definition before you build on it

Run one query for each check.

- **Activation is not automatic.** If most signups reach the milestone within a day, check whether the event fires by itself, for example during signup. When you chose the definition, pick a later milestone. When the user or the team chose it, keep it and tell the user what you found.
- **The steps share an actor.** If a signup-to-activation funnel converts 0% while both events have volume in the date range, check who each event is recorded for. When they are recorded for different people in the same account, aggregate the funnel by the account group, or choose another event.
- **The query finishes.** Run the activation funnel and the active-users trend once. If either times out or runs out of memory, do not retry it unchanged: shorten the range or use a lighter event.

**Ask when the project does not answer.** If you find no definition, ask the user before you build. Send one message with at most three questions: what counts as active, what counts as activated, and whether to count people or accounts. If you cannot ask, choose, and put your choices first in your summary and in the dashboard description.

**Count one thing.** Choose people or accounts for the whole dashboard, and count that unit in every tile. For a B2B product (`posthog:project-get` shows the business model and the account group), count accounts.

## Rhythm

The rhythm sets the interval, the date range, and what the headline row means. Use weekly unless people use the product most days and the user asks for a daily view.

| Rhythm | Interval | Dashboard `filters`                           | The headline row shows |
| ------ | -------- | --------------------------------------------- | ---------------------- |
| Weekly | `week`   | `date_from: "-12wStart"`, `date_to: "-1wEnd"` | The last complete week |
| Daily  | `day`    | `date_from: "-29d"`, `date_to: "-1d"`         | Yesterday              |

Both ranges hold only complete periods, so no chart ends in a partial bar that looks like a drop.
The daily range starts on the same weekday as yesterday, so the change on a headline tile compares like with like.

## Layout

Box is `w` x `h` on the 12-column grid. Rows follow the order of the table.

| Section    | Tile                    | Insight                                                                                                                                       | Box    |
| ---------- | ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| Headline   | Active users            | Trends, core action, unique count per period, Metric with `latest`                                                                            | 3 x 3  |
| Headline   | New signups             | Trends, signup event, unique count per period, Metric with `latest`                                                                           | 3 x 3  |
| Headline   | Newly activated         | Trends, activation event, unique count per period, Metric with `latest`                                                                       | 3 x 3  |
| Headline   | New paying customers    | Trends, paid event, unique count per period, Metric with `latest`. Without a paid event, leave this tile out and make the other three `4 x 3` | 3 x 3  |
| Growth     | Active users            | Trends, core action, unique count per period, line                                                                                            | 6 x 5  |
| Growth     | New signups             | Trends, signup event, unique count per period, line                                                                                           | 6 x 5  |
| Growth     | New, returning, dormant | Lifecycle on the core action                                                                                                                  | 12 x 5 |
| Activation | Signup to activated     | Funnel, steps: signup, 0-2 steps between, activation                                                                                          | 6 x 5  |
| Activation | Activation rate         | The same funnel with `funnelVizType: "trends"` and incomplete periods hidden                                                                  | 6 x 5  |
| Engagement | What people do          | Trends, 5-8 main actions as series, unique count, `ActionsBarValue`                                                                           | 6 x 5  |
| Engagement | Periods active          | Stickiness on the core action, at the rhythm's interval                                                                                       | 6 x 5  |
| Retention  | Signup cohort retention | Retention: start event signup, return event core action, first-time, one row per period                                                       | 12 x 5 |

Headline tile names are about 20 characters at most. A longer name is cut off at three columns wide.

"Unique count" means unique users (`math: "dau"`) when the dashboard counts people, and unique accounts (`math: "unique_group"` with the group type index) when it counts accounts.
For accounts, also aggregate the funnel, lifecycle, and retention tiles by the account group.
The headline signup number must equal the funnel's first step for the same period.

**The headline row holds counts, not rates.** Activation, conversion, and retention rates belong to a cohort: the people who signed up in a period and what they did later. A trends formula cannot follow a cohort. It divides this week's activations by this week's signups, which can read twice the true rate. The exact rate is in the "Activation rate" tile.

"Newly activated" needs an activation event that happens once per user. If the event can repeat, use `math: "first_time_for_user"` (`"first_time_for_group"` when you count accounts), or leave the tile out when that query is too heavy to finish.
Do not place it where a reader will divide it by new signups: most first activations in a week come from accounts that signed up earlier.

For "What people do", choose the actions from the core action's own events or from the most-used custom events, one per product area. Leave out pageviews, autocapture, and system events.

## Adapt

- **Daily.** Use the daily row of the rhythm table. Leave out the lifecycle and retention tiles. They need whole weeks, and a daily range cuts the first and last week short.
- **Revenue.** If a paid event exists and the user asked about money or runs the business, add a "Revenue" section: new paying customers per period, and a signup-to-paid funnel with a window long enough for the sale.
  Revenue amounts need a numeric property or a warehouse source. Never estimate an amount from event counts.
- **A named framework.** For AARRR and similar, name the sections after the stages and keep the headline row as it is. A stage the project has no clean event for (often referral) gets no section. Say so in your summary instead of relabeling something else.
- **Mobile.** Add one chart of active users by platform or app version. Do not add the breakdown to the main chart.
- **Early product.** With fewer than about 100 active users per period, show counts and say the sample is small.
- **A set.** If the user wants depth on activation, retention, or revenue, keep this dashboard as the overview and build one more dashboard per area.

## Avoid

- An estimated rate in the headline row.
- Pageviews or sessions as the measure of an active user.
- Cumulative totals in the headline row. They only go up and hide a decline.
- People in one tile and accounts in the next.
- A SQL copy of a governed metric as a tile. It ignores the dashboard date range and drifts from the metric. Build the tile from the metric's events and filters.
- Retention defined as "any event". Use the core action as the return event.

## Tell the user

End with a short summary that leads with the definitions you used for active, signed up, and activated, and where each came from.
Then list any tile that is empty and why, and anything you want the user to confirm.
