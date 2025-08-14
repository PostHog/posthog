import { LemonBanner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { actionEditLogic } from '../logics/actionEditLogic'
import { actionLogic } from '../logics/actionLogic'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { SceneSection } from '~/layout/scenes/SceneContent'

export function ActionHogFunctions(): JSX.Element | null {
    const { action } = useValues(actionLogic)
    const { hasCohortFilters, actionChanged, showCohortDisablesFunctionsWarning } = useValues(
        actionEditLogic({ id: action?.id, action })
    )
    if (!action) {
        return null
    }

    return (
        <SceneSection
            className="@container"
            title="Connected destinations"
            description="Actions can be used as filters for destinations such as Slack or Webhook delivery"
        >
            {showCohortDisablesFunctionsWarning ? (
                <LemonBanner type="error">Adding a cohort filter will disable all connected destinations!</LemonBanner>
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
        </SceneSection>
    )
}
