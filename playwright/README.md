# End-to-End Testing

## Running playwright

Note: All animations and transitions are disabled for E2E tests for speed reasons.
If you absolutely need them, turn them back on by setting the env variable `DISABLE_ANIMATIONS="false"`

### Local: no pre-existing instance

Spin up a full local E2E environment (backend, frontend, docker services, Playwright UI):

```bash
hogli test:e2e
```

This will start a setup with playwright, backend, celery-worker, frontend, docker-compose stack and reset-db process.

1. Ensure all processes are up and running without errors before executing any tests
2. Trigger `reset-db` process from mprocs's UI to start with a clean backend
3. Launch desired tests using Playwright's UI

### Local: with pre-existing instance

If you do not have playwright browsers installed they will be automatically installed prior to running the test command

```bash
LOGIN_USERNAME="mylogin@example.com" LOGIN_PASSWORD="1234abcd" pnpm test:playwright:local
```

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
