# End-to-End Testing

## `/e2e/` directory contains all the end-to-end tests.

### to run the old cypress tests, run the following command:

```bash
START_CYPRESS=1 ./bin/e2e-test-runner
```

### to run the new playwright tests, run the following command:

```bash
START_PLAYWRIGHT=1 ./bin/e2e-test-runner
``` 

### to run the new playwright tests against an already locally running PostHog instance

NB there are some differences between a running dev instance and the instance started by the e2e script so not all tests will pass when running in this mode

```bash
LOGIN_USERNAME='my@email.address' LOGIN_PASSWORD="the-password" BASE_URL='http://localhost:8010' pnpm --filter=@posthog/playwright exec playwright test --ui
```
