import { actions, connect, kea, listeners, path } from 'kea'
import posthog from 'posthog-js'

import { LemonDialog, LemonInput, LemonTextArea, lemonToast } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { HogFunctionTypeType } from '~/types'

import { humanizeHogFunctionType } from '../hog-function-utils'
import type { hogFunctionRequestModalLogicType } from './hogFunctionRequestModalLogicType'

export const hogFunctionRequestModalLogic = kea<hogFunctionRequestModalLogicType>([
    path(() => ['scenes', 'hog-functions', 'list', 'hogFunctionRequestModalLogic']),
    connect(() => ({
        values: [userLogic, ['user'], featureFlagLogic, ['featureFlags']],
    })),
    actions({
        openFeedbackDialog: (type: HogFunctionTypeType, name: string = '') => ({ type, name }),
    }),

    listeners(() => ({
        openFeedbackDialog: async ({ type, name }, breakpoint) => {
            await breakpoint(100)
            const humanizedType = humanizeHogFunctionType(type)
            LemonDialog.openForm({
                title: `What ${humanizedType} would you like to see?`,
                initialValues: { name: name },
                errors: {
                    name: (x) => (!x ? 'Required' : undefined),
                },
                description: undefined,
                content: (
                    <div className="deprecated-space-y-2">
                        <LemonField name="name" label={`Name of the ${humanizedType}`}>
                            <LemonInput placeholder="e.g. PostHog" autoFocus />
                        </LemonField>
                        <LemonField name="details" label="Additional information" showOptional>
                            <LemonTextArea
                                placeholder={`Any extra details about what you would need this ${humanizedType} to do or your overall goal`}
                            />
                        </LemonField>
                    </div>
                ),
                onSubmit: async (values) => {
                    posthog.capture(`cdp hog function feedback`, { type, ...values })
                    lemonToast.success('Thank you for your feedback!')
                },
            })
        },
    })),
])
