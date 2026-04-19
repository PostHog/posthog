import { ActionStepType, EventType, RecordingEventType } from '~/types'

import { applyDataAttributeSelector, applySubmitProperty, elementsToAction } from './createActionFromEvent'

type AutocaptureEvent = (EventType | RecordingEventType) & { event: '$autocapture' }

export function isAutocaptureWithElements(event: EventType | RecordingEventType): event is AutocaptureEvent {
    return event.event === '$autocapture' && event.elements?.length > 0
}

export function eventToActionStep(event: AutocaptureEvent, dataAttributes: string[]): ActionStepType {
    const step: ActionStepType = {
        event: '$autocapture',
        ...(event.properties.$current_url ? { url: event.properties.$current_url, url_matching: 'exact' } : {}),
        ...elementsToAction(event.elements),
    }

    applyDataAttributeSelector(step, event.elements, dataAttributes)
    applySubmitProperty(step, event.properties)

    return step
}
