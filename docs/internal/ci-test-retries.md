# CI retries and Trunk

Retry failed tests in the test runner and retain each failed attempt in the uploaded JUnit report.
A passing retry can pass CI.
A test that fails its retry must still fail the test command.
The existing Trunk gate can clear failures for quarantined tests.
An upload failure does not turn a failed test command into a pass.

## Suites connected to Trunk

| Suite                                           | Retry budget                                 | Failed-attempt report                                                                                           |
| ----------------------------------------------- | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Backend pytest: core, Temporal, products        | One in CI                                    | Separate JUnit reports retain failed attempts; see [PR #101493](https://github.com/PostHog/posthog/pull/101493) |
| Frontend Jest, Node.js Jest, replay-shared Jest | One in CI                                    | Shared setup enables error recording; patched `jest-junit` emits retry children                                 |
| Storybook                                       | Two, as configured by its test runner        | Patched `jest-junit` emits retry children                                                                       |
| Playwright E2E                                  | One in normal CI; zero in the audit workflow | Built-in JUnit reporter with `includeRetries: true`                                                             |
| Rust nextest                                    | One in the CI profile                        | Built-in JUnit retry children                                                                                   |

Jest retries after the other tests in the file.
Local Jest commands do not enable the shared CI retry setting.
Existing suite-specific overrides still apply.

The `jest-junit` patch preserves the existing test names, file paths, counts, and final results.
It adds `flakyFailure` for a passing retry and `rerunFailure` for earlier attempts when the final attempt fails.
`logErrorsBeforeRetry: true` is required so Jest retains `retryReasons` for the reporter.

Trunk CLI 0.15.4 is pinned in the shared upload action and the inline Playwright upload step.
Its [parser and regression tests](https://github.com/trunk-io/analytics-cli/blob/0.15.4/context/src/junit/parser.rs) retain retry children as separate attempts.
The published [Trunk Playwright guide](https://docs.trunk.io/flaky-tests/get-started/frameworks/playwright) and [pytest guide](https://docs.trunk.io/flaky-tests/get-started/frameworks/pytest) still recommend disabling retries.
Use the released parser behavior and validate the actual report when a runner changes.

## Validation and rollout

Use a temporary test that fails once and then passes, plus a test that fails every attempt.
Check the command exit code and the XML for both cases.
Run `trunk-analytics-cli validate --junit-paths '<report path>'` before uploading; this command does not upload data.
The [Playwright reporter reference](https://playwright.dev/docs/test-reporters#junit-reporter) and [nextest retry reference](https://nexte.st/docs/features/retries/) describe their report settings.

After merge, inspect one recovered test from each suite in Trunk.
Confirm that it has both a failed and a passed attempt under the same identity.
Check the existing Engineering analytics attempt counts and recovered-test outcomes.
Track quarantine growth and CI failures after the change: more visible retry failures can produce more quarantine decisions.

## Other test jobs

This configuration covers the suites with Trunk upload gates.
Standalone Vitest jobs, Go jobs, Rust doctests, and separate desktop workflows need their own report and exit-code checks before adopting the same policy.
Lint, type checks, builds, test discovery errors, and process crashes do not receive a test retry.
