# Visual Regression Tests

We're using Playwright to run visual regression tests against Storybook. To create reference images that are consistent between development and CI we run Playwright in an Ubuntu Docker container.

## Workflow

### Writing or updating a test

0. Use fixtures

    _tbd_

1. Perform the actions to get to the state

    - Get inspiration from one of the existing tests. Lemon Button and Insights scene are good examples.

    - Use Playwright's [codegen feature](https://playwright.dev/docs/codegen-intro) to record user interactions interactively e.g. `pnpm playwright codegen "http://localhost:6006/iframe.html?args=&id=scenes-app-insights--trends-line&viewMode=story"`.

    - Use Playwright's [debug mode](https://playwright.dev/docs/debug) to inspect an existing test in a headed browser e.g. `pnpm playwright test --debug e2e-vrt/scenes-app/mytest.spec.ts:17:5`. Sprinkle in `await page.pause()` in your test to stop at specific lines.

2. Add screenshot expectations:

    - Capture the whole page (we rarely use this):

        ```ts
        await expect(page).toHaveScreenshot({ fullPage: true })
        ```

    - Capture content within a container element:

        ```ts
        const locator = page.locator('#storybook-root')
        await expect(locator).toHaveScreenshot()
        ```

    - Suggested Storybook container elements:
        - `#root` for components and
        - `main` for scenes

3. Generate the reference images (you need to have Storybook running locally, i.e. on the Docker host machine):

    ```sh
    docker compose -f docker-compose.playwright.yml run -it --build -e STORYBOOK_URL=http://host.docker.internal:6006 playwright pnpm test:visual-regression
    ```

    > If your `docker compose version` is lower than 2.13, you won't be able to use the `--build` flag. Instead, first run `docker compose -f docker-compose.playwright.yml build playwright`, and then the above `run` command - without the `--build` arg.

    Open the generated report locally with `pnpm dlx playwright show-report` to see test results (they are mounted local in docker volume)

### Renaming or deleting tests

When deleting or renaming a test, (re-)move the respective reference images as well or delete `rm -rf playwright/**/*.png` and re-create (see above) them.

## Troubleshooting

### The CI run on GitHub fails for any reason

Troubleshoot by viewing the Playwright report: Click on "Details" next to the failing workflow, click on "Summary" and download the artifact file. Extract this file and navigate to it in a terminal to then run `pnpm dlx playwright show-report`.

### Your locally generated images, don't verify CI checks

GitHub is running tests against a temporary merge commit (to ensure tests still pass after being merged), meaning any changes currently in master will be present in the images generated in the CI run. If you suspect this is the case, merge master into your branch and push again.

### The screenshots look wrong and I want to debug it live

If you run any playwright command with `PWDEBUG=1` then it will run in "headfull" mode so that you can see the browser and look into what is going on
