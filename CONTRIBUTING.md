There are many ways to contribute to PostHog. We want to help developers know exactly how users are interacting with their stuff, in a way that doesn't send data to 3rd parties.

# Creating a PR

Just create a new pull request if you want to make an update.

We recommend you create an issue if one doesn't already exist, and continue the conversation on the issue to get more info/alignment on what to build.

For more information on how we review PRs, please refer to our [handbook](https://posthog.com/handbook/engineering/how-we-review).

# External PRs: what to expect

We welcome contributions. A few quick notes so you know how we operate:

- PRs are triaged/assigned via CODEOWNERS or manual assignment to the owning team.
- The current week's [Support Hero](https://posthog.com/handbook/engineering/support-hero) for the owning team is usually the first point of contact, but customer support takes priority. Reviews can be delayed when support load is high.
- Expect acknowledgement when we have bandwidth; thorough reviews may come later. It's fine if this takes a few days to a couple of weeks depending on load.
- We sometimes close PRs that are out of scope, would add long-term maintenance burden, or go stale. You're always welcome to reopen with updates.

Before we do a full review, please:

- Ensure that you've run tests locally and resolved any merge conflicts before submitting.
- Respond to automated review feedback (e.g. Greptile comments) where applicable.
- Keep the change focused; add tests and docs where it meaningfully improves clarity.
- Follow existing patterns and conventions in the areas you touch.

Escalation/deferral can happen for security-sensitive or critical paths, unclear product impact, or when support load is high—another engineer may pick it up later. We sometimes reward helpful contributions with merch even if a PR doesn’t merge.

# Issues

Spotted a bug? Has deployment gone wrong? Do you have user feedback? Raise an issue for the fastest response.

... or pick up and fix an issue if you want to do a Pull Request.

## Issues with paid features

We prefer not to accept external contributions for paid features. If you don't see the feature on your local build, it's most probably paid.

# Feature requests

Raise an issue for these and tag it as an Enhancement. We love every idea. Please give us as much context on the why as possible.

# Features

We strive to keep our [roadmap](https://posthog.com/roadmap) up-to-date, while our [WIP page](https://posthog.com/wip) lists the features we're actively working on. We aren't generally expecting contributions towards these fronts since we've already decided who's going to be working on it and have allocated enough resources towards it.

As a rule of thumb - if you wanna work on a specific feature that fits with helping developers understand product usage and/or extending PostHog to ingest more of their customer's data, we'll generally like it.

If you are at all unsure, just raise it as an enhancement issue first, and we'll attempt to respond very quickly.
