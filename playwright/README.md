# End-to-End Testing

## `/e2e/` directory contains all the end-to-end tests

to run the new playwright tests, run the following command:

```bash
./bin/e2e-test-runner
```

to run the new playwright tests against an already locally running PostHog instance

```bash
LOGIN_USERNAME='my@email.address' LOGIN_PASSWORD="the-password" BASE_URL='http://localhost:8010' pnpm --filter=@posthog/playwright exec playwright test --ui
```

### For all of these

you might need to install playwright with `pnpm --filter=@posthog/playwright exec playwright install`

## Writing tests

### Flaky tests are almost always due to not waiting for the right thing

Consider adding a better selector, an intermediate step like waiting for URL or page title to change, or waiting for a critical network request to complete.

### Useful output from playwright

If you write a selector that is too loose and matches multiple elements, playwright will output all the matches. With a better selector for each

```text
Error: locator.click: Error: strict mode violation: locator('text=Set a billing limit') resolved to 2 elements:
1) <span class="LemonButton__content">Set a billing limit</span> aka getByTestId('billing-limit-input-wrapper-product_analytics').getByRole('button', { name: 'Set a billing limit' })
2) <span class="LemonButton__content">Set a billing limit</span> aka getByTestId('billing-limit-input-wrapper-session_replay').getByRole('button', { name: 'Set a billing limit' })
```

<!-- Test 4-core runner performance -->
