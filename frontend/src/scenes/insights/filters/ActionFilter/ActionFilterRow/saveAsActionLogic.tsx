import { actions, afterMount, kea, listeners, path } from 'kea'
import posthog from 'posthog-js'

import api from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { actionsModel } from '~/models/actionsModel'

import { LocalFilter } from '../entityFilterLogic'
import type { saveAsActionLogicType } from './saveAsActionLogicType'
import { filterToActionStep, generateActionNameFromFilter } from './saveAsActionUtils'

export const saveAsActionLogic = kea<saveAsActionLogicType>([
    path(['scenes', 'insights', 'filters', 'ActionFilter', 'ActionFilterRow', 'saveAsActionLogic']),
    actions({
        openSaveAsActionDialog: (filter: LocalFilter) => ({ filter }),
    }),
    afterMount(() => {
        actionsModel.mount()
    }),
    listeners({
        openSaveAsActionDialog: ({ filter }) => {
            const suggestedName = generateActionNameFromFilter(filter)

            LemonDialog.openForm({
                title: 'Save as action',
                initialValues: { actionName: suggestedName },
                shouldAwaitSubmit: true,
                errors: {
                    actionName: (value: string) => (!value?.trim() ? 'Action name is required' : undefined),
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
                    const step = filterToActionStep(filter)
                    try {
                        const action = await api.actions.create({ name: actionName, steps: [step] })
                        actionsModel.findMounted()?.actions.loadActions()
                        lemonToast.success(
                            <>
                                Action created. <Link to={urls.action(action.id)}>View action</Link>
                            </>
                        )
                    } catch (error) {
                        posthog.captureException(error, { action: 'save-as-action' })
                        lemonToast.error('Failed to create action. Please try again.')
                    }
                },
            })
        },
    }),
])
