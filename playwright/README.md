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

## 2. /`e2e-vrt/` directory contains all the end-to-end visual regression tests.
