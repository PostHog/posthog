# SDK Doctor Branch Notes

*This is just branch-specific documentation - will remove before a PR*

### Current SDK Doctor MVP Goals:

#### Detect outdated SDK versions of most popular SDKs
- Calls the GitHub API to compare `$lib_version` on recent events against the most recent releases, alerts for SDKs that are >2 releases behind the latest version
- Also has hardcoded minimum versions for critical updates (e.g., `posthog-js` <1.85.0)
- Uses GitHub API with 24-hour caching and semantic version parsing
  
#### Detect Multiple SDK Initializations
- Alerts when the same SDK is initialized multiple times on the same page (Same URL + different session IDs + short time gaps (<30s) + same SDK version)
- Clears automatically when sustained normal behavior is observed (5+ events same session)

#### Detect Feature Flags Called Before Initialization
- Catches feature flags being called before PostHog has finished loading by analyzing timing of `$feature_flag_called` events vs initialization events
- Handles multiple flag event types and auto-clears after proper flag usage patterns

**Implementation:** Frontend TypeScript logic that processes recent events within a 10-minute window, with persistent detection state.