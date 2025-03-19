# Storybook 8 Migration Guide

This document outlines the changes made to migrate from Storybook 7 to Storybook 8.

## Main Changes Made

1. Updated package.json dependencies:

    - Updated core packages to version 8.x
    - Replaced deprecated packages:
        - Removed `@storybook/addons` → Added `@storybook/manager-api` and `@storybook/preview-api`
        - Added `@storybook/test` (replaces `@storybook/testing-library`)
    - Added explicit React dependency

2. Updated preview.tsx:

    - Disabled automatic actions with `actions: { argTypesRegex: false }`
    - Added TypeScript interface for global window to fix TypeScript errors
    - Imported React explicitly for JSX support

3. Created example files to show new patterns:
    - Updated action handling to use `fn()` from `@storybook/test`
    - Added examples of play functions with explicit actions

## Required Changes For All Stories

### 1. Update action handlers

Replace automatic action handlers with explicit `fn()` calls:

```typescript
// Before (Storybook 7)
export default {
    component: Button,
    // Actions were inferred from props starting with "on"
}

// After (Storybook 8)
import { fn } from '@storybook/test'

export default {
    component: Button,
    args: {
        onClick: fn(), // Explicitly define actions
        onHover: fn(),
    },
}
```

### 2. Update imports

```typescript
// Before
import { userEvent, within } from '@storybook/testing-library'

// After
import { userEvent, within, expect } from '@storybook/test'
```

### 3. Update play functions

```typescript
// Play functions now need explicit actions defined
const story = {
    args: {
        onClick: fn(),
    },
    play: async ({ args, canvasElement }) => {
        await userEvent.click(within(canvasElement).getByRole('button'))
        await expect(args.onClick).toHaveBeenCalled()
    },
}
```

## Additional Changes

### Testing with composeStories

The play function returned by `composeStories` is now potentially undefined:

```typescript
// Before
await Primary.play(...)

// After
await Primary.play?.(...) // Optional chaining
```

### Manager API Changes

If you have custom addons that use manager API:

```typescript
// Before
import { addons } from '@storybook/addons'
import { API } from '@storybook/api'

// After
import { addons } from '@storybook/manager-api'
import { API } from '@storybook/manager-api'
```

## For More Information

Refer to the official [Storybook Migration Guide](https://storybook.js.org/docs/migration-guide) for complete details.
