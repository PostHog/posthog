# Storybook visual regression tests

In CI we use playwright to load our storybooks scenes and take snapshots of them

If they have changed we commit those snapshots back to the PR

This lets you check if you have broken the UI unexpectedly or changed it in the way you expected

You can check `test-runner.ts` to see how this is done

Uses `"@storybook/test-runner"` see: https://storybook.js.org/docs/writing-tests/test-runner

## to run locally

before you do this... 🤷

in one terminal

```bash
pnpm --filter=@posthog/frontend storybook
```

in another

```bash
pnpm exec playwright install
pnpm --filter=@posthog/storybook test:visual:debug
```
