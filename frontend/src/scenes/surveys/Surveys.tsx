import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { VersionCheckerBanner } from 'lib/components/VersionChecker/VersionCheckerBanner'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { cn } from 'lib/utils/css-classes'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import MaxTool from 'scenes/max/MaxTool'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { SurveyFeedbackButton } from 'scenes/surveys/components/SurveyFeedbackButton'
import { SurveysTable } from 'scenes/surveys/components/SurveysTable'
import { captureMaxAISurveyCreationException } from 'scenes/surveys/utils'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType, ActivityScope, ProductKey } from '~/types'

import { SurveySettings, SurveysDisabledBanner } from './SurveySettings'
import { SURVEY_CREATED_SOURCE } from './constants'
import { SurveysTabs, surveysLogic } from './surveysLogic'

export const scene: SceneExport = {
    component: Surveys,
    logic: surveysLogic,
    settingSectionId: 'environment-surveys',
}

function NewSurveyButton(): JSX.Element {
    const { loadSurveys, addProductIntent } = useActions(surveysLogic)
    const { user } = useValues(userLogic)

    return (
        <MaxTool
            identifier="create_survey"
            initialMaxPrompt="Create a survey to collect "
            suggestions={[
                'Create an NPS survey for customers who completed checkout',
                'Create a feedback survey asking about our new dashboard',
                'Create a product-market fit survey for trial users',
                'Create a quick satisfaction survey for support interactions',
            ]}
            context={{
                user_id: user?.uuid,
            }}
            callback={(toolOutput: {
                survey_id?: string
                survey_name?: string
                error?: string
                error_message?: string
            }) => {
                addProductIntent({
                    product_type: ProductKey.SURVEYS,
                    intent_context: ProductIntentContext.SURVEY_CREATED,
                    metadata: {
                        survey_id: toolOutput.survey_id,
                        source: SURVEY_CREATED_SOURCE.MAX_AI,
                        created_successfully: !toolOutput?.error,
                    },
                })

                if (toolOutput?.error || !toolOutput?.survey_id) {
                    return captureMaxAISurveyCreationException(toolOutput.error, SURVEY_CREATED_SOURCE.MAX_AI)
                }

                // Refresh surveys list to show new survey, then redirect to it
                loadSurveys()
                router.actions.push(urls.survey(toolOutput.survey_id))
            }}
            position="bottom-right"
            active={!!user?.uuid && userHasAccess(AccessControlResourceType.Survey, AccessControlLevel.Editor)}
            className={cn('mr-3')}
        >
            <AccessControlAction
                resourceType={AccessControlResourceType.Survey}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonButton size="small" to={urls.surveyTemplates()} type="primary" data-attr="new-survey">
                    <span className="pr-3">New survey</span>
                </LemonButton>
            </AccessControlAction>
        </MaxTool>
    )
}

function Surveys(): JSX.Element {
    const { tab } = useValues(surveysLogic)

    const { setTab } = useActions(surveysLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Surveys].name}
                description={sceneConfigurations[Scene.Surveys].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Surveys].iconType || 'default_icon_type',
                }}
                actions={
                    <>
                        <SurveyFeedbackButton />
                        <NewSurveyButton />
                    </>
                }
            />
            <SurveysDisabledBanner />
            <LemonTabs
                activeKey={tab}
                onChange={(newTab) => setTab(newTab as SurveysTabs)}
                tabs={[
                    { key: SurveysTabs.Active, label: 'Active' },
                    { key: SurveysTabs.Archived, label: 'Archived' },
                    { key: SurveysTabs.Notifications, label: 'Notifications' },
                    { key: SurveysTabs.History, label: 'History' },
                    { key: SurveysTabs.Settings, label: 'Settings' },
                ]}
                sceneInset={true}
            />
            {tab === SurveysTabs.Settings && <SurveySettings />}
            {tab === SurveysTabs.Notifications && (
                <>
                    <p>Get notified whenever a survey result is submitted</p>
                    <LinkedHogFunctions type="destination" subTemplateIds={['survey-response']} />
                </>
            )}

            {tab === SurveysTabs.History && <ActivityLog scope={ActivityScope.SURVEY} />}

            {(tab === SurveysTabs.Active || tab === SurveysTabs.Archived) && (
                <>
                    <VersionCheckerBanner />
                    <SurveysTable />
                </>
            )}
        </SceneContent>
    )
}
