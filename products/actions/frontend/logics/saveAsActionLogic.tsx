import { actions, afterMount, kea, listeners, path } from 'kea'
import posthog from 'posthog-js'

import api from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Link } from 'lib/lemon-ui/Link'
import { autoCaptureEventToDescription } from 'lib/utils'
import { eventToActionStep, isAutocaptureWithElements } from 'scenes/activity/explore/saveActionFromEvent'
import {
    filterToActionStep,
    generateActionNameFromFilter,
} from 'scenes/insights/filters/ActionFilter/ActionFilterRow/saveAsActionUtils'
import { LocalFilter } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { urls } from 'scenes/urls'

import { actionsModel } from '~/models/actionsModel'
import { ActionStepType, EventType, RecordingEventType } from '~/types'

import type { saveAsActionLogicType } from './saveAsActionLogicType'

export interface OpenSaveAsActionDialogPayload {
    suggestedName: string
    step: ActionStepType
    createInFolder?: string
}

export function buildActionNameValidator(existingActionNames: Iterable<string>): (value: string) => string | undefined {
    const existing = new Set([...existingActionNames].map((name) => name.trim()).filter(Boolean))
    return (value: string) => {
        const trimmed = value?.trim()
        if (!trimmed) {
            return 'Action name is required'
        }
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

export const saveAsActionLogic = kea<saveAsActionLogicType>([
    path(['products', 'actions', 'frontend', 'logics', 'saveAsActionLogic']),
    actions({
        saveFromFilter: (filter: LocalFilter) => ({ filter }),
        saveFromEvent: (event: EventType | RecordingEventType, dataAttributes: string[]) => ({
            event,
            dataAttributes,
        }),
        openSaveAsActionDialog: (payload: OpenSaveAsActionDialogPayload) => payload,
    }),
    afterMount(() => {
        actionsModel.mount()
    }),
    listeners(({ actions }) => ({
        saveFromFilter: ({ filter }) => {
            actions.openSaveAsActionDialog({
                suggestedName: generateActionNameFromFilter(filter),
                step: filterToActionStep(filter),
            })
        },
        saveFromEvent: ({ event, dataAttributes }) => {
            if (!isAutocaptureWithElements(event)) {
                return
            }
            actions.openSaveAsActionDialog({
                suggestedName: autoCaptureEventToDescription(event),
                step: eventToActionStep(event, dataAttributes),
                createInFolder: 'Unfiled/Actions',
            })
        },
        openSaveAsActionDialog: ({ suggestedName, step, createInFolder }) => {
            const existingActionNames = (actionsModel.findMounted()?.values.actions ?? []).map((a) => a.name ?? '')
            LemonDialog.openForm({
                title: 'Save as action',
                initialValues: { actionName: suggestedName },
                shouldAwaitSubmit: true,
                errors: {
                    actionName: buildActionNameValidator(existingActionNames),
                },
                content: (
                    <LemonField name="actionName" label="Action name">
                        <LemonInput
                            data-attr="save-as-action-name"
                            placeholder="e.g., Clicked signup button"
                            autoFocus
                        />
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
        },
    })),
])
