### Max Context
Scene logics can expose a `maxContext` selector to provide relevant context to MaxAI.

To do so:

1.  Import the necessary types and helpers:

    ```typescript
    import { MaxContextSelector, createMaxContextHelpers } from 'scenes/max/maxTypes'
    ```

2.  Add a `maxContext` selector that returns MaxContextSelector:

    ```typescript
    selectors({
        maxContext: [
            (s) => [s.dashboard],
            (dashboard): MaxContextSelector => {
                if (!dashboard) {
                    return []
                }
                return [createMaxContextHelpers.dashboard(dashboard)]
            },
        ],
    })
    ```

3.  For multiple context items:
    ```typescript
    maxContext: [
        (s) => [s.insight, s.events],
        (insight, events): MaxContextSelector => {
            const context = []
            if (insight) context.push(createMaxContextHelpers.insight(insight))
            if (events?.length) context.push(...events.map(createMaxContextHelpers.event))
            return context
        },
    ]
    ```

The maxContextLogic will automatically detect and process these context items.
Use the helper functions to ensure type safety and consistency.

Currently, these types of contexts are supported:
- Dashboards
- Insights
- Events
- Actions

Caveat: we currently support these types of insights: trends, funnels, retention, custom SQL.
This means that if you expose a dashboard with custom queries, these will show up in the frontend logic,
but won't be actually available to Max in the backend.

To add support custom queries, refer to the README in ee/hogai
