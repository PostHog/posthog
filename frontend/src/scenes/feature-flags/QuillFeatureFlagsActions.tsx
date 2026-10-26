import { IconPlus } from '@posthog/icons'
import { Button, ButtonGroup } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FeedbackSurveyButton } from 'lib/components/FeedbackSurveyButton/FeedbackSurveyButton'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { QuillNewFeatureFlagMenu } from './QuillNewFeatureFlagMenu'

export interface QuillFeatureFlagsActionsProps {
    feedbackSurveyId: string
    showRulesV2Editor: boolean
    rulesV2DisabledReason: string | null | undefined
    newFeatureFlagUrl: string
}

export function QuillFeatureFlagsActions({
    feedbackSurveyId,
    showRulesV2Editor,
    rulesV2DisabledReason,
    newFeatureFlagUrl,
}: QuillFeatureFlagsActionsProps): JSX.Element {
    const createDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.FeatureFlag,
        AccessControlLevel.Editor
    )

    return (
        <>
            <FeedbackSurveyButton surveyId={feedbackSurveyId} data-attr="feature-flags-feedback-button" />
            {showRulesV2Editor && (
                <AccessControlAction
                    resourceType={AccessControlResourceType.FeatureFlag}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <Button
                        variant="outline"
                        render={<LinkPrimitive to={urls.featureFlagNew({ format: 'rules_v2' })} />}
                        disabledReason={rulesV2DisabledReason}
                        data-attr="new-rules-v2-feature-flag"
                    >
                        New rules v2 flag
                    </Button>
                </AccessControlAction>
            )}
            <ButtonGroup>
                <Shortcut
                    name="NewFeatureFlag"
                    keybind={[keyBinds.new]}
                    intent="New feature flag"
                    interaction="click"
                    scope={Scene.FeatureFlags}
                    disabledReason={createDisabledReason}
                >
                    <Button
                        variant="primary"
                        render={<LinkPrimitive to={newFeatureFlagUrl} />}
                        disabledReason={createDisabledReason}
                        tooltip="New feature flag"
                        data-attr="new-feature-flag"
                    >
                        <IconPlus />
                        New
                    </Button>
                </Shortcut>
                <QuillNewFeatureFlagMenu disabledReason={createDisabledReason} />
            </ButtonGroup>
        </>
    )
}
