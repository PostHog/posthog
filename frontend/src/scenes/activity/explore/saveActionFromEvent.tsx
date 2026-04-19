import { autoCaptureEventToDescription } from 'lib/utils'

import { ActionStepType, EventType, RecordingEventType } from '~/types'

import { applyDataAttributeSelector, applySubmitProperty, elementsToAction } from './createActionFromEvent'

type AutocaptureEvent = (EventType | RecordingEventType) & { event: '$autocapture' }

export function isAutocaptureWithElements(event: EventType | RecordingEventType): event is AutocaptureEvent {
    return event.event === '$autocapture' && event.elements?.length > 0
}

export function eventToActionStep(event: EventType | RecordingEventType, dataAttributes: string[]): ActionStepType {
    const hasElements = (event.elements?.length ?? 0) > 0
    const hasUrl = Boolean(event.properties.$current_url)
    const supportsUrl = event.event === '$pageview' || event.event === '$autocapture'

    const step: ActionStepType = {
        event: event.event,
        ...(hasUrl && supportsUrl ? { url: event.properties.$current_url, url_matching: 'exact' } : {}),
        ...(hasElements ? elementsToAction(event.elements) : {}),
    }

    if (hasElements) {
        applyDataAttributeSelector(step, event.elements, dataAttributes)
    }
    applySubmitProperty(step, event.properties)

    return step
}

export function eventToSuggestedActionName(event: EventType | RecordingEventType): string {
    if (event.event === '$autocapture') {
        return autoCaptureEventToDescription(event)
    }
    if (event.event === '$pageview') {
        const url = event.properties.$current_url
        if (url) {
            try {
                return `Pageview on ${new URL(url).pathname}`
            } catch {
                // fall through to generic Pageview label
            }
        }
        return 'Pageview action'
    }
    return `${event.event} event`
}
