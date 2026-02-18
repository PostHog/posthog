# End-to-End Testing

## Running tests

Spin up a full local E2E environment (backend, frontend, docker services, Playwright UI):

```bash
./bin/e2e-test-runner
```

This uses `bin/mprocs-e2e.yaml` under the hood. If you need to reset the E2E database,
trigger the `reset-db` process in the mprocs UI.

To run tests against an already-running PostHog instance:

```bash
LOGIN_USERNAME='my@email.address' LOGIN_PASSWORD="the-password" BASE_URL='http://localhost:8010' pnpm --filter=@posthog/playwright exec playwright test --ui
```

You might need to install Playwright first: `pnpm --filter=@posthog/playwright exec playwright install`

## Writing tests

### Flaky tests are almost always due to not waiting for the right thing

Consider adding a better selector, an intermediate step like waiting for URL or page title to change, or waiting for a critical network request to complete.

### Useful output from Playwright

If you write a selector that is too loose and matches multiple elements, Playwright will output all the matches. With a better selector for each:

```text
Error: locator.click: Error: strict mode violation: locator('text=Set a billing limit') resolved to 2 elements:
1) <span class="LemonButton__content">Set a billing limit</span> aka getByTestId('billing-limit-input-wrapper-product_analytics').getByRole('button', { name: 'Set a billing limit' })
2) <span class="LemonButton__content">Set a billing limit</span> aka getByTestId('billing-limit-input-wrapper-session_replay').getByRole('button', { name: 'Set a billing limit' })
```
