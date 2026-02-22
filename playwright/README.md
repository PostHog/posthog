# End-to-End Testing

## Running playwright

All animations and transitions are disabled for E2E tests for speed reasons.
If you absolutely need them, turn them back on by setting the env variable `DISABLE_ANIMATIONS="false"`

If you do not have playwright installed and/or configured, the first time you run this it will download a few browsers so it can use them in later tests

### Local: no pre-existing instance

Spin up a full local E2E environment (backend, frontend, docker services, Playwright UI):

Via hogcli, if you configured your env with flox:

```bash
hogli test:e2e
```

### Local: with pre-existing instance

THis will hardcode BASE_URL to `http://localhost:8000`

**Pre-requisites**

1. Ensure you have a dev environment running `hogli start`
1. Ensure you have exported LOGIN_USERNAME and LOGIN_PASSWORD if you want to re-use an existing account, otherwise a default will be used

**Run the tests with UI**

```bash
pnpm run test:ui:local
```

**Run the tests headless**

```bash
pnpm run test:local
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
