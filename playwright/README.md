# End to End Testing

<<<<<<< HEAD
## `/e2e/` directory contains all the end-to-end tests.
=======
`/e2e/` directory contains all the end-to-end tests.
>>>>>>> master

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
