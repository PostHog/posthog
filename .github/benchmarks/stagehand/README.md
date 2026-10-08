# Throwaway Stagehand E2E experiment

This draft ports the ten scenarios in `playwright/e2e/auth.spec.ts` and
`playwright/e2e/before-onboarding.spec.ts` to Stagehand 4.1.0. The baseline runs
those existing specs unchanged. PostHog's normal E2E workflow stays unchanged.

## What this can answer

Stagehand v4 is not a drop-in replacement. Its
[migration guide](https://docs.stagehand.dev/v4/migrations/playwright) explicitly
requires porting and omits Playwright's runner, locators, assertions, network
mocking and auto-waiting. This experiment asks whether real flows can preserve
their assertions after a port, and whether the port reduces their CI test time.

The port keeps Playwright's test runner, retrying value assertions and API-based
workspace setup. Browser actions use Stagehand's local extension runtime,
configured according to the [browser docs](https://docs.stagehand.dev/v4/configuration/browser).
It uses no AI, model key or Browserbase service. Unsupported mocks and request
waits used elsewhere in the suite are outside this first port. Passing these
ten scenarios does not certify the full suite or its visual checks.

## Fixed measurement protocol

- A small CI job initializes the same shared browser bootstrap before the
  three full-stack jobs start. Startup failures stop the experiment early.
- The workflow copies stack preparation from `ci-e2e-playwright.yml`, including
  the schema restore, frontend production build, ingestion services, four
  Granian workers and six test workers on `depot-ubuntu-24.04-8`.
- Both lanes use the same commit, stack, full Chromium executable, viewport,
  timeouts and one-retry policy. The baseline uses full Chromium for an equal
  binary comparison; normal E2E may use Playwright's headless shell.
- Stagehand has one context per browser. The port launches a fresh browser per
  test to preserve isolation; that startup and all explicit waits are timed.
  The baseline keeps Playwright's existing context-per-test lifecycle.
- Chrome 148 restricts extension installation to a trusted pipe client. The
  port uses Playwright's launcher and browser CDP session to install Stagehand's
  bundled extension, then attaches Stagehand by extension ID over loopback.
  It keeps the common binary and includes this bootstrap in the timings.
- Three independent CI hosts run one excluded warmup pair and five measured
  pairs each. Driver order alternates within hosts and the starting order
  reverses across hosts. Hosts remain separate populations.
- Each command timer includes runner startup, workspace/login fixtures, browser
  initialization, the actual test bodies, assertion waits and teardown. Every
  action is awaited. The scenarios assert URLs, submitted field values, rendered
  errors, settings headings, insight content and cross-tab logout effects.
- The report requires the same ten distinct test titles and successful final
  outcomes on both sides. Terminal failures, skips, missing reports or incomplete
  pairs invalidate a speed comparison. Retries remain in operational CI timings
  and failure counts; clean driver timing requires zero retries. Both warmup lanes run even after one
  fails, then measurement stops. Nothing removes outliers or retries a CI job.
- Artifacts retain raw Playwright JSON, every command wall time, per-test
  attempts, screenshots on failures, commit/source/lock hashes and cache hits.
  The report shows medians, ranges and a seeded paired-bootstrap 95% interval.
  A difference within host variation is inconclusive; all three hosts must
  agree before reporting a direction.
- CPU profiles and Node/Chromium/app process samples run after the measurements.
  These diagnostics do not enter timing summaries. Inspect them to identify
  the limiter before claiming a winner, including browser launch overhead,
  assertion polling and application response time.

## CI time and cost validation

The experiment shares stack preparation once per host. The complete experiment
job duration is therefore not either driver's normal job cost. GitHub's job and
step timestamps provide setup and install durations; metadata also records
setup through readiness and the additional Stagehand install. Compare cache
hits and resolved container versions before comparing separate hosts.

For this bounded workload, estimate a normal job as common setup plus one lane's
test command, adding the Stagehand install to that lane. Include failed runs and
retries when evaluating expected cost. Use the same runner billing rate, and
label any duration-times-rate calculation as an estimate. Actual dollar savings
require billing data. Do not extrapolate these ten auth scenarios to the whole
E2E suite or multiply the vendor's advertised speedup by the whole CI bill.

Review all three artifacts and their diagnostics before deciding whether to
expand the port. No local browser run or local timing is evidence for this
experiment. Local checks are limited to discovery, formatting, workflow lint
and tests of the result validator. Artifacts expire after seven days. Remove
this directory and the workflow after the experiment.
