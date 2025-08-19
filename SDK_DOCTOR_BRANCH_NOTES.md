# SDK Doctor Branch Notes

*This is just branch-specific documentation - will remove before a PR*

### Current SDK Doctor MVP Goals:

#### Detect outdated SDK versions of most popular SDKs
- Calls the GitHub API to compare `$lib_version` on recent events against the most recent releases, alerts for SDKs that are >2 releases behind the latest version
- Also has hardcoded minimum versions for critical updates (e.g., `posthog-js` <1.85.0)
- Uses GitHub API with 24-hour caching and semantic version parsing

#### Detect Feature Flags Called Before Initialization
- Catches feature flags being called before PostHog has finished loading by analyzing timing of `$feature_flag_called` events vs the first event in the session.
- Handles multiple flag event types and auto-clears after proper flag usage patterns

**Implementation:** Frontend TypeScript logic that processes recent events within a 10-minute window for SDK version, 30-minutes for feature flag timing, with persistent detection state.

---

## The below moved to post-MVP
Going to need to figure out how to either add a property to the next event being sent, or send new events without increasing usage count, so we can detect warnings like `You have already initialized PostHog!` sent from SDKs,like those in [this file](https://github.com/PostHog/posthog-js/blob/f6fdd8ecd8b011162e34263f7096e190b4b9c453/packages/browser/src/posthog-core.ts#L464).

### Detect Multiple SDK Initializations
- Alerts when the same SDK is initialized multiple times on the same page (Same URL + different session IDs + short time gaps (<30s) + same SDK version)
- Clears automatically when sustained normal behavior is observed (5+ events same session)

#### Post-MVP release ToDo
- Add a "Do not notify me about this again" (with an undo page/list)
- Add big Max for add'l help
- detect when a feature flag  uses a cohort which relies on another cohort which has since been deleted.
- Use `Teams` activity history to look for issues, e.g. [this thread](https://posthog.slack.com/archives/C03PB072FMJ/p1754557639664509)
- Add a backend tool behind a FF for CS folks to view a list of their accounts who have out-of date SDK versions

**Maybe/misc list:**
Add a misc info section, for non-warning info, e.g. [Capturing events more than one project at the same time](https://posthog.com/docs/libraries/js#running-more-than-one-instance-of-posthog-at-the-same-time)
