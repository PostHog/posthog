# Feature usage tracking

- **Every feature is tracked end to end.** A user's path through a feature, from entry to outcome, emits events that show whether people start it, finish it, and where they drop off.
- **Features adjacent to your work get tracking too.** A feature is adjacent when it shares a scene or a user flow with your change. When an adjacent feature has no tracking, add it in the same change.
- **Check usage of tracked adjacent features.** Run a subagent that queries each tracked adjacent feature's usage over the last 6 months.
  - Fewer than 100 interactions a week counts as low usage. Zero events in 6 months is the extreme case of low usage.
  - Before you act on low usage, confirm the tracking fires: trigger the feature locally and check that the events arrive. Missing events can mean broken tracking, not an unused feature.
  - The PR description lists each low-usage feature with its event, date range, and weekly count. The PR is the record of the finding.
  - A Slack post about low usage comes from a bot, never from a person's account. Slack shows a post made with a person's connector or token as a message they wrote, so do not post that way.
  - Post a low-usage feature in Slack only when it has been in production for about 6 months or more, and no feature flag, beta tag, or alpha tag gates it. A newer or gated feature stays in the PR description only. This keeps the channel free of noise.
  - Post the findings in the platform UX Slack channel (Channel ID: `C08499A7REU`) only through a bot, and start the post with "Automated usage check from <PR link>". When your session has no bot route to Slack, do not post: the PR reviewer takes the findings to the channel.
  - The decision to keep or remove a low-usage feature is made in that channel. Do not remove a feature before that decision.
