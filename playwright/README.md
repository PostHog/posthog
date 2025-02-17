# End to End Testing

## 1. `/e2e/` directory contains all the end-to-end tests.

to run the old cypress tests, run the following command:

```bash
START_CYPRESS=1 ./bin/e2e-test-runner
```

to run the new playwright tests, run the following command:

```bash
START_PLAYWRIGHT=1 ./bin/e2e-test-runner
``` 

to run the new playwright tests against an already locally running PostHog instance
```bash
LOGIN_USERNAME='my@email.address' LOGIN_PASSWORD="the-password" BASE_URL='http://localhost:8010' pnpm exec playwright test --ui
```

## 2. /`e2e-vrt/` directory contains all the end-to-end visual regression tests.
