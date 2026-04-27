import { useValues } from 'kea'

import { LemonBanner, LemonCollapse } from '@posthog/lemon-ui'

import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'

import { ActionType } from '~/types'

import { actionEditLogic } from '../logics/actionEditLogic'
import { actionLogic } from '../logics/actionLogic'

export function ActionHogFunctions(): JSX.Element | null {
    const { action, tabId } = useValues(actionLogic)
    return !action ? null : <Functions action={action} tabId={tabId} />
}

const Functions = ({ action, tabId }: { action: ActionType; tabId?: string }): JSX.Element => {
    const { hasCohortFilters, actionChanged, showCohortDisablesFunctionsWarning } = useValues(
        actionEditLogic({ id: action?.id, action, tabId })
    )
    return (
        <LemonCollapse
            defaultActiveKey="connected-destinations"
            panels={[
                {
                    key: 'connected-destinations',
                    header: {
                        children: (
                            <div className="py-1">
                                <div className="font-semibold">Connected destinations</div>
                                <div className="text-secondary text-sm font-normal">
                                    Actions can be used as filters for destinations such as Slack or Webhook delivery
                                </div>
                            </div>
                        ),
                    },
                    content: (
                        <div className="@container deprecated-space-y-2">
                            {showCohortDisablesFunctionsWarning ? (
                                <LemonBanner type="error">
                                    Adding a cohort filter will disable all connected destinations!
                                </LemonBanner>
                            ) : null}

                            <LinkedHogFunctions
                                type="destination"
                                forceFilterGroups={[
                                    {
                                        actions: [
                                            {
                                                id: `${action.id}`,
                                                name: action.name,
                                                type: 'actions',
                                            },
                                        ],
                                    },
                                ]}
                                newDisabledReason={
                                    hasCohortFilters
                                        ? "Action with cohort filters can't be used in realtime destinations"
                                        : actionChanged
                                          ? 'Please first save the action to create a destination'
                                          : undefined
                                }
                            />
                        </div>
                    ),
                },
            ]}
        />
    )
}
