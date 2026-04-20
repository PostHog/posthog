import posthog from 'posthog-js'

import api from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Link } from 'lib/lemon-ui/Link'
import { autoCaptureEventToDescription } from 'lib/utils'
import {
    applyDataAttributeSelector,
    applySubmitProperty,
    elementsToAction,
} from 'scenes/activity/explore/createActionFromEvent'
import {
    filterToActionStep,
    generateActionNameFromFilter,
} from 'scenes/insights/filters/ActionFilter/ActionFilterRow/saveAsActionUtils'
import { LocalFilter } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { urls } from 'scenes/urls'

import { actionsModel } from '~/models/actionsModel'
import { ActionStepType, EventType, RecordingEventType } from '~/types'

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

export function buildActionNameValidator(
    getExistingActionNames: () => Iterable<string>
): (value: string) => string | undefined {
    return (value: string) => {
        const trimmed = value?.trim()
        if (!trimmed) {
            return 'Action name is required'
        }
        const existing = new Set([...getExistingActionNames()].map((name) => name.trim()).filter(Boolean))
        if (existing.has(trimmed)) {
            return 'An action with this name already exists'
        }
        return undefined
    }
}

function getServerErrorMessage(error: unknown): string | undefined {
    const data = (error as { data?: Record<string, unknown> } | undefined)?.data
    if (!data || typeof data !== 'object') {
        return undefined
    }
    if (typeof data.detail === 'string') {
        return data.detail
    }
    const firstFieldMessage = (value: unknown): string | undefined =>
        Array.isArray(value) && typeof value[0] === 'string' ? value[0] : undefined
    return firstFieldMessage(data.name) ?? firstFieldMessage(data.non_field_errors)
}

interface OpenSaveAsActionDialogPayload {
    suggestedName: string
    step: ActionStepType
    createInFolder?: string
}

export function openSaveAsActionDialog({ suggestedName, step, createInFolder }: OpenSaveAsActionDialogPayload): void {
    actionsModel.mount()
    LemonDialog.openForm({
        title: 'Save as action',
        initialValues: { actionName: suggestedName },
        shouldAwaitSubmit: true,
        errors: {
            actionName: buildActionNameValidator(() =>
                (actionsModel.findMounted()?.values.actions ?? []).map((a) => a.name ?? '')
            ),
        },
        content: (
            <LemonField name="actionName" label="Action name">
                <LemonInput data-attr="save-as-action-name" placeholder="e.g., Clicked signup button" autoFocus />
            </LemonField>
        ),
        onSubmit: async ({ actionName }) => {
            try {
                const action = await api.actions.create({
                    name: actionName,
                    steps: [step],
                    ...(createInFolder ? { _create_in_folder: createInFolder } : {}),
                })
                actionsModel.findMounted()?.actions.loadActions()
                lemonToast.success(
                    <>
                        Action created. <Link to={urls.action(action.id)}>View action</Link>
                    </>
                )
            } catch (error) {
                posthog.captureException(error, { action: 'save-as-action' })
                lemonToast.error(getServerErrorMessage(error) ?? 'Failed to create action. Please try again.')
            }
        },
    })
}

export function saveActionFromFilter(filter: LocalFilter): void {
    openSaveAsActionDialog({
        suggestedName: generateActionNameFromFilter(filter),
        step: filterToActionStep(filter),
    })
}

export function saveActionFromEvent(event: EventType | RecordingEventType, dataAttributes: string[]): void {
    openSaveAsActionDialog({
        suggestedName: eventToSuggestedActionName(event),
        step: eventToActionStep(event, dataAttributes),
        createInFolder: 'Unfiled/Actions',
    })
}
