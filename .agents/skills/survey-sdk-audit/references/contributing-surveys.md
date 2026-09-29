# Contributing survey changes

Use this guide when a survey change needs work in the PostHog repository or SDK source.
For configuration and response diagnosis, use the published `debugging-surveys` skill.

## Repository setup

Use the [local repo registry](local-repos.md) to find and reuse checkouts.
Run the commands from the `survey-sdk-audit` skill directory:

```sh
python3 scripts/repos.py init
python3 scripts/repos.py ensure posthog-js
```

| Concern              | Repo                                                                        | Where to look                                                            |
| -------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Product UI + backend | this monorepo (PostHog/posthog)                                             | UI: `frontend/src/scenes/surveys/`, backend: `products/surveys/backend/` |
| Web SDK              | [PostHog/posthog-js](https://github.com/PostHog/posthog-js)                 | `packages/browser/`                                                      |
| React Native SDK     | [PostHog/posthog-js](https://github.com/PostHog/posthog-js) (same monorepo) | `packages/react-native/`                                                 |
| iOS SDK              | [PostHog/posthog-ios](https://github.com/PostHog/posthog-ios)               | survey rendering + eligibility                                           |
| Android SDK          | [PostHog/posthog-android](https://github.com/PostHog/posthog-android)       | eligibility (delegate-based UI)                                          |
| Flutter SDK          | [PostHog/posthog-flutter](https://github.com/PostHog/posthog-flutter)       | Dart rendering; native iOS/Android handles eligibility                   |
| Public docs          | [PostHog/posthog.com](https://github.com/PostHog/posthog.com)               | `contents/docs/surveys/`                                                 |

Check the branch before you change a repository.
Search for symbols instead of using stored line numbers.

## Implementation

1. Make the backend and UI changes in the PostHog repository.
2. Decide which SDKs support the feature. State any platform limits in the documentation and PR.
3. Implement the SDK changes. Web and React Native share `posthog-js`. Flutter uses native eligibility logic and Dart rendering.
4. Update the public survey documentation and the feature parity table in the published `debugging-surveys` skill.
5. Follow the SDK audit in the parent skill to check version requirements and coverage.
