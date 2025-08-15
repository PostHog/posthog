import { LemonBanner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { actionEditLogic } from '../logics/actionEditLogic'
import { actionLogic } from '../logics/actionLogic'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { SceneSection } from '~/layout/scenes/SceneContent'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { cn } from 'lib/utils/css-classes'

export function ActionHogFunctions(): JSX.Element | null {
    const { action } = useValues(actionLogic)
    const { hasCohortFilters, actionChanged, showCohortDisablesFunctionsWarning } = useValues(
        actionEditLogic({ id: action?.id, action })
    )
    const { featureFlags } = useValues(featureFlagLogic)
    const newSceneLayout = featureFlags[FEATURE_FLAGS.NEW_SCENE_LAYOUT]

    if (!action) {
        return null
    }

    return (
        <SceneSection
            className={cn(!newSceneLayout && '@container my-4 deprecated-space-y-2')}
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
