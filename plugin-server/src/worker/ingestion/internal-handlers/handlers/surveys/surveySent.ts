import { PluginEvent } from '@posthog/plugin-scaffold'

import { InternalEventHandler, InternalEventHandlerContext } from '../../registry'

// check if the survey needs to be stopped when a response is submitted
export const surveySentHandler: InternalEventHandler = {
    name: 'surveys sent',
    events: ['survey sent'],

    async handle(event: PluginEvent, context: InternalEventHandlerContext): Promise<void> {
        const surveyId = event.properties?.['$survey_id']
        if (surveyId && context.celery) {
            await context.celery.applyAsync('posthog.tasks.tasks.stop_surveys_reached_target', [], {
                survey_id: surveyId,
            })
        }
    },
}
