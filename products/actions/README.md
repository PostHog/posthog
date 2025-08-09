# Actions Product

This demonstrates the new hierarchical manifest structure for PostHog products, enabling auto-generated breadcrumbs and better organization.

## Hierarchical Manifest Structure

The manifest now supports a `children` property for organizing related functionality hierarchically:

```typescript
export const manifest: ProductManifest = {
    name: 'Actions',
    urls: { ... },
    routes: { ... },
    // Hierarchical organization for auto-generated breadcrumbs
    children: {
        DataManagement: {
            name: 'Data management',
            children: {
                Actions: {
                    name: 'Actions',
                    scenes: {
                        ActionNew: { ... },
                        ActionEdit: { ... },
                        // etc.
                    },
                },
            },
        },
    },
}
```

## Auto-Generated Breadcrumbs

The hierarchy automatically generates breadcrumbs like:
- **Data management** > **Actions** > **New action**
- **Data management** > **Actions** > **Edit action**

## Build Process

1. The `build-products.mjs` script processes the `children` structure
2. Scenes are flattened while preserving hierarchy information
3. URLs and routes are generated normally
4. Breadcrumb utilities can use the hierarchy for consistent navigation

## Usage Example

```typescript
// In your logic file
import { breadcrumbPatterns } from 'lib/utils/breadcrumbUtils'

selectors({
    breadcrumbs: [
        (s) => [s.action],
        (action): Breadcrumb[] => breadcrumbPatterns.dataManagement.actions(
            action?.name || undefined,
            !!action?.id // isEdit
        ),
    ],
})
```

This approach:
- ✅ Keeps URLs pointing to your products folder implementation
- ✅ Auto-generates consistent breadcrumbs
- ✅ Maintains hierarchical organization
- ✅ Reduces boilerplate code
- ✅ Makes navigation patterns reusable 