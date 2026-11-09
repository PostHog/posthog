# Feature usage tracking

- **Every feature is tracked end to end.** A user's path through a feature, from entry to outcome, emits events that show whether people start it, finish it, and where they drop off.
- **Features adjacent to your work get tracking too.** A feature is adjacent when it shares a scene or a user flow with your change. When an adjacent feature has no tracking, add it in the same change.
- **Check usage of tracked adjacent features.** Run a subagent that queries each tracked adjacent feature's usage over the last 6 months.
  - Fewer than 100 interactions a week counts as low usage. Zero events in 6 months is the extreme case of low usage.
  - Before you act on low usage, confirm the tracking fires: trigger the feature locally and check that the events arrive. Missing events can mean broken tracking, not an unused feature.
  - Post each low-usage feature and its usage numbers in the platform UX Slack channel (Channel ID: `C08499A7REU`). The decision to keep or remove the feature is made there. Do not remove a feature before that decision.
