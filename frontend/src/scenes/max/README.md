### Max Context

Scene logics can expose a `maxContext` selector to provide relevant context to MaxAI.

To do so:

1. Import the necessary types and helpers:

   ```typescript
   import { MaxContextInput, createMaxContextHelpers } from 'scenes/max/maxTypes'
   ```

2. Add a `maxContext` selector that returns MaxContextInput[]:

   ```typescript
   selectors({
     maxContext: [
       (s) => [s.dashboard],
       (dashboard): MaxContextInput[] => {
         if (!dashboard) {
           return []
         }
         return [createMaxContextHelpers.dashboard(dashboard)]
       },
     ],
   })
   ```

3. For multiple context items:

   ```typescript
   maxContext: [
     (s) => [s.insight, s.events],
     (insight, events): MaxContextInput[] => {
       const context = []
       if (insight) context.push(createMaxContextHelpers.insight(insight))
       if (events?.length) context.push(...events.map(createMaxContextHelpers.event))
       return context
     },
   ]
   ```

The maxContextLogic will automatically detect and process these context items.
Use the helper functions to ensure type safety and consistency.

Currently, these context entities are supported:

- Dashboards
- Insights
- Events
- Actions
- Error tracking issues

## Adding new context entity types

If you want to add new entities, you need to extend `maxContextLogic.ts`. Follow the established pattern:

### 1. Define types in `maxTypes.ts`

```typescript
// Add a new context type enum value
export enum MaxContextType {
  // ... existing types
  MY_ENTITY = 'my_entity',
}

// Add context interface (what gets sent to backend)
export interface MaxMyEntityContext {
  type: MaxContextType.MY_ENTITY
  id: string
  name?: string | null
}

// Add context input type (what scene logics return)
type MaxMyEntityContextInput = {
  type: MaxContextType.MY_ENTITY
  data: { id: string; name?: string | null }
}

// Add to the union types
export type MaxContextItem /* existing types */ = MaxMyEntityContext
export type MaxContextInput /* existing types */ = MaxMyEntityContextInput

// Add helper function
export const createMaxContextHelpers = {
  // ... existing helpers
  myEntity: (entity: { id: string; name?: string | null }): MaxMyEntityContextInput => ({
    type: MaxContextType.MY_ENTITY,
    data: entity,
  }),
}
```

### 2. Add state and actions in `maxContextLogic.ts`

```typescript
actions({
    // ... existing actions
    addOrUpdateContextMyEntity: (data: { id: string; name?: string | null }) => ({ data }),
    removeContextMyEntity: (id: string) => ({ id }),
}),
reducers({
    // ... existing reducers
    contextMyEntities: [
        [] as MaxMyEntityContext[],
        {
            addOrUpdateContextMyEntity: (state, { data }) =>
                addOrUpdateEntity(state, {
                    type: MaxContextType.MY_ENTITY,
                    id: data.id,
                    name: data.name,
                }),
            removeContextMyEntity: (state, { id }) => removeEntity(state, id),
            resetContext: () => [],
        },
    ],
}),
```

### 3. Handle selection in `handleTaxonomicFilterChange`

```typescript
// For direct selection from taxonomic filter
if (groupType === TaxonomicFilterGroupType.MyEntities) {
    actions.addOrUpdateContextMyEntity(item as { id: string; name?: string })
    return
}

// For selection from MaxAIContext (scene context items)
if (_item.type === MaxContextType.MY_ENTITY) {
    actions.addOrUpdateContextMyEntity({
        id: _item.value as string,
        name: _item.name ?? null,
    })
    return null
}
```

### 4. Convert scene context in `sceneContext` selector

```typescript
case MaxContextType.MY_ENTITY:
    return {
        type: MaxContextType.MY_ENTITY,
        id: item.data.id,
        name: item.data.name,
    } as MaxMyEntityContext
```

### 5. Add to `contextOptions` selector (for dropdown display)

```typescript
} else if (item.type == MaxContextType.MY_ENTITY) {
    options.push({
        id: item.id,
        name: item.name || `Entity ${item.id}`,
        value: item.id,
        type: MaxContextType.MY_ENTITY,
        icon: IconMyEntity,
    })
}
```

### 6. Add to `taxonomicGroupTypes` selector

```typescript
groupTypes.push(
  // ... existing types
  TaxonomicFilterGroupType.MyEntities
)
```

### 7. Include in `compiledContext` selector

```typescript
// Add to selector dependencies
(s: any) => [/* existing deps */, s.contextMyEntities, s.sceneContext],

// Combine manual selections with auto-added scene context
const sceneMyEntities = sceneContext.filter(
    (item): item is MaxMyEntityContext => item.type === MaxContextType.MY_ENTITY
)
const allMyEntities = [...contextMyEntities, ...sceneMyEntities]
if (allMyEntities.length > 0) {
    const uniqueEntities = new Map<string, MaxMyEntityContext>()
    allMyEntities.forEach((e) => uniqueEntities.set(e.id, e))
    context.my_entities = Array.from(uniqueEntities.values())
}
```

### 8. Update `hasData` selector

Include `contextMyEntities` in the array of states checked for data.

### Key points

- Scene logics provide context via `maxContext` selector → auto-added to context
- Users can also manually select items from the taxonomic filter
- Both sources are combined and deduplicated in `compiledContext`
- Items appear in `contextOptions` dropdown for user visibility/selection

Caveat: we currently support these types of insights: trends, funnels, retention, custom SQL.
This means that if you expose a dashboard with custom queries, these will show up in the frontend logic,
but won't be actually available to Max in the backend.

To add support for **reading** custom queries, refer to the README in ee/hogai

To add support for **generating** insights with custom queries, talk to the Max AI team
