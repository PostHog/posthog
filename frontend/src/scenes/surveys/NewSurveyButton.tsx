import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { surveysLogic } from './surveysLogic'

export function useTrackAddNewSurvey(): () => void {
    const { addProductIntent } = useActions(surveysLogic)
    return () =>
        addProductIntent({
            product_type: ProductKey.SURVEYS,
            intent_context: ProductIntentContext.SURVEY_ADD_NEW,
        })
}

export function NewSurveyButton(): JSX.Element {
    const trackAddNewClick = useTrackAddNewSurvey()
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return (
        <AccessControlAction resourceType={AccessControlResourceType.Survey} minAccessLevel={AccessControlLevel.Editor}>
            <Shortcut
                name="NewSurvey"
                keybind={[keyBinds.new]}
                intent="New survey"
                interaction="click"
                scope={Scene.Surveys}
            >
                {todayRailNav ? (
                    <Button
                        variant="primary"
                        render={<LinkPrimitive to={urls.surveyWizard()} />}
                        data-attr="new-survey"
                        tooltip="New survey"
                        onClick={trackAddNewClick}
                    >
                        New survey
                    </Button>
                ) : (
                    <LemonButton
                        size="small"
                        to={urls.surveyWizard()}
                        type="primary"
                        data-attr="new-survey"
                        tooltip="New survey"
                        onClick={trackAddNewClick}
                    >
                        New survey
                    </LemonButton>
                )}
            </Shortcut>
        </AccessControlAction>
    )
}
