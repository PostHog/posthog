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

If you want to add new entities, you need to extend `maxContextLogic.ts`, slightly more difficult, but doable, check how other entities are supported and start from there.

Caveat: we currently support these types of insights: trends, funnels, retention, custom SQL.
This means that if you expose a dashboard with custom queries, these will show up in the frontend logic,
but won't be actually available to Max in the backend.

To add support for **reading** custom queries, refer to the README in ee/hogai

To add support for **generating** insights with custom queries, talk to the Max AI team
