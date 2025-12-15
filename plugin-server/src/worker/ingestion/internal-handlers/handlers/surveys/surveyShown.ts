import { PluginEvent } from '@posthog/plugin-scaffold'

import { InternalEventHandler, InternalEventHandlerContext } from '../../registry'

// update $last_seen_survey_date when a user sees a survey
export const surveyShownHandler: InternalEventHandler = {
    name: 'surveys shown',
    events: ['survey shown'],

    handle(event: PluginEvent, _context: InternalEventHandlerContext): Promise<void> {
        event.properties = {
            ...(event.properties || {}),
            $set: {
                ...(event.properties?.['$set'] || {}),
                $last_seen_survey_date: event.timestamp || new Date().toISOString(),
            },
        }
        return Promise.resolve()
    },
}
