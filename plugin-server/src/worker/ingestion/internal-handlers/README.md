# internal-handlers

this is a set of event handlers that allow you to "do X when we get Y event" during event ingestion.

`internalHandlerStep` triggers all handlers attached to a given event, and runs after `normalizeEventStep` in `runner.ts`

## how-to

1. create a handler in `handlers/<your-product>/<some-event-handler>.ts`, give it a name and specify relevant events:

```typescript
import { PluginEvent } from '@posthog/plugin-scaffold'
import { InternalEventHandler, InternalEventHandlerContext } from '../../registry'

export const myEventHandler: InternalEventHandler = {
    name: 'unique event handler name',
    events: ['list of', 'relevant events'],

    async handle(event: PluginEvent, context: InternalEventHandlerContext): Promise<void> {
        // do something
    },
}
```

2. register your handler in `index.ts`

```typescript
import { myEventHandler } from './handlers/my-product/myEventHandler'

internalEventHandlerRegistry.register(myEventHandler)
```

## examples

### update person property

when we get a `survey shown` event, we want to update a person property `$last_seen_survey_date`.

```typescript
async handle(event: PluginEvent, _context: InternalEventHandlerContext): Promise<void> {
    event.properties = {
        ...(event.properties || {}),
        $set: {
            ...(event.properties?.['$set'] || {}),
            $last_seen_survey_date: event.timestamp || new Date().toISOString(),
        },
    }
},
```

see `handlers/surveys/surveyShown.ts`

### trigger celery job

when we get a `survey sent` event, we want to check if the survey needs to be disabled, e.g. it has been set to "stop survey after collecting N responses"

```typescript
async handle(event: PluginEvent, context: InternalEventHandlerContext): Promise<void> {
    const surveyId = event.properties?.['$survey_id']
    if (surveyId && context.celery) {
        await context.celery.applyAsync('posthog.tasks.tasks.stop_surveys_reached_target', [], {
            survey_id: surveyId,
        })
    }
},
```

see `handlers/surveys/surveySent.ts`
