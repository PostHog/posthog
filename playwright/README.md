# Playwright End-to-End Testing

There are two types of tests in here.

1. `/e2e/` - These are the end-to-end tests that run in the browser. They are written in TypeScript and use Playwright.

you might have fun writing these

2. `/e2e-vrt/` - These are the visual regression tests that run in the browser. They are written in TypeScript and use Playwright.

you probably won't touch this folder

## Running the tests

### End-to-End Tests

You might need to run 

`pnpm exec playwright install`

then

`START_CYPRESS=0 ./bin/e2e-test-runner --skip-all-setup`

this is to run setup and start the development server

then

`pnpm exec playwright test --ui`