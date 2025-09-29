# SDK Doctor Beta README
(soon to be replaced by actual docs)

### Current SDK Doctor functionality 🩺

#### Detects outdated versions of 12 PostHog SDKs
- **Smart alert thresholds by device type**: Desktop/web events trigger alerts when SDKs are 3+ releases behind *and* 48+ hours old, while mobile app events only alert for versions >8 weeks old (to reduce noise from slower rollout cycles)
- **Volume-adaptive performance**: Automatically adjusts event sampling based on customer volume to balance detection accuracy with performance. Scans occur at session start, with autoscans every 30 minutes thereafter. On-demand scan is available via menu
- **Indicators for outdatedness**: 🟢 Current, 🟡 Close enough, and 🔴 Outdated
- **12 PostHog SDKs supported**: Web, Python, React Native, Node.js, Flutter, iOS, Android, Go, PHP, .NET, Ruby, Elixir
- **Self-help links**: We display links to SDK changelogs and documentation pages for easy upgrade guidance
- **Server-side caching**: GitHub release version and release date info is cached server-side for 6 hours (for speed and to avoid rate-limiting)

#### Detect Feature Flags called too soon
- **Too soon**: Catches `Feature flag called` events occuring before any other events in the session
- **Smart bootstrapping detection**: No alerts for bootstrapped flags
- **Example event links**: Provides links to the first feature flag called event detected, to help with debugging
- Handles multiple flags at once, auto-clears alert after proper flag usage patterns detected


---

## Post-beta

### Detect multiple SDK init attempts
- Alert when we detect attempts to initialize the same SDK multiple times on the same page in the same session

#### Under consideration for post-beta:
- Add a `Do not notify me about this again for...` option
- Add Max for add'l help
- Detect when a feature flag uses a cohort which relies on another cohort which has since been deleted (until/unless that functionality gets added to cohorts)
- Use `Teams` activity history to look for issues, e.g. [this thread](https://posthog.slack.com/archives/C03PB072FMJ/p1754557639664509)
- Add a backend tool behind a FF for CS folks to view a list of their accounts who have out-of date SDK versions
- Relay outdated SDK information to HogHero for more support context