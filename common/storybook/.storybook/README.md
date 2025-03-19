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

# Storybook 8 Migration Guide

This Storybook instance has been updated to Storybook 8. Here are the key changes that affect our stories:

## Actions Changes

In Storybook 8, the automatic action creation (based on `onX` prop names) has been removed. You must now explicitly define actions using the `fn()` function from `@storybook/test`.

### Before (Storybook 7):

```typescript
// Actions were automatically created for onXxx props
export default {
    component: Button,
}

export const ButtonClick = {
    play: async ({ args, canvasElement }) => {
        await userEvent.click(within(canvasElement).getByRole('button'))
        // args.onClick was automatically a jest spy in 7.0
        await expect(args.onClick).toHaveBeenCalled()
    },
}
```

### After (Storybook 8):

```typescript
import { fn } from '@storybook/test'

export default {
    component: Button,
    args: {
        onClick: fn(), // Explicitly create a spy
    },
}

export const ButtonClick = {
    play: async ({ args, canvasElement }) => {
        await userEvent.click(within(canvasElement).getByRole('button'))
        await expect(args.onClick).toHaveBeenCalled()
    },
}
```

## Testing Library Changes

-   Replace imports from `@storybook/testing-library` with `@storybook/test`:

```typescript
// Before
import { userEvent, within } from '@storybook/testing-library'

// After
import { userEvent, within } from '@storybook/test'
```

## Play Functions in Tests

When using `composeStories` or `composeStory`, the play function is now potentially undefined:

```typescript
const { Primary } = composeStories(stories);

// Before
await Primary.play(...)

// After
await Primary.play?.(...)  // Optional chaining if you don't care if play exists
await Primary.play!(...)   // Non-null assertion if you want a runtime error when play doesn't exist
```

## Additional Notes

-   Tab addons are now routed to a query parameter instead of path
-   Manager addons are now rendered with React 18
-   Several deprecated packages and APIs have been removed

For the full migration guide, see the [Storybook documentation](https://storybook.js.org/docs/migration-guide).
