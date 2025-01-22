# Storybook visual regression tests

In CI we use playwright to load our storybooks scenes and take snapshots of them

If they have changed we commit those snapshots back to the PR

This lets you check if you have broken the UI unexpectedly or changed it in the way you expected

You can check `test-runner.ts` to see how this is done

## to run locally

before you do this... 🤷

in one terminal 
```bash
pnpm storybook
```

in another

```bash
pnpm test:visual:debug
```