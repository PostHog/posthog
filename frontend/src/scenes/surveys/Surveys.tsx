import { useActions, useValues } from 'kea'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { SurveyFeedbackButton } from 'scenes/surveys/components/SurveyFeedbackButton'
import { SurveyNotificationsList } from 'scenes/surveys/components/SurveyNotificationsList'
import { SurveysTable } from 'scenes/surveys/components/SurveysTable'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

import { surveysEmptyState } from 'products/surveys/frontend/emptyState/surveysEmptyState'

import { SURVEY_CREATED_SOURCE } from './constants'
import { DuplicateToProjectModal } from './DuplicateToProjectModal'
import { NewSurveyButton } from './NewSurveyButton'
import { SurveySettings, SurveysDisabledBanner } from './SurveySettings'
import { SurveysTabs, surveysLogic } from './surveysLogic'
import { SurveysSceneMenuBar } from './SurveysSceneMenuBar'

export const scene: SceneExport = {
    component: Surveys,
    logic: surveysLogic,
    productKey: ProductKey.SURVEYS,
    emptyState: surveysEmptyState,
}

function Surveys(): JSX.Element {
    const { tab } = useValues(surveysLogic)
    const { setTab, handleMaxSurveyCreated } = useActions(surveysLogic)

    return (
        <SceneContent>
            <SurveysSceneMenuBar />
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
                maxToolProps={{
                    identifier: 'create_survey',
                    initialMaxPrompt: 'Create a survey to collect ',
                    suggestions: [
                        'Create an NPS survey for customers who completed checkout',
                        'Create a feedback survey asking about our new dashboard',
                        'Create a product-market fit survey for trial users',
                        'Create a quick satisfaction survey for support interactions',
                    ],
                    context: {},
                    callback: (toolOutput) => handleMaxSurveyCreated(toolOutput, SURVEY_CREATED_SOURCE.MAX_AI),
                }}
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
            {tab === SurveysTabs.Notifications && <SurveyNotificationsList />}

            {tab === SurveysTabs.History && <ActivityLog scope={ActivityScope.SURVEY} />}

            {(tab === SurveysTabs.Active || tab === SurveysTabs.Archived) && <SurveysTable />}
            <DuplicateToProjectModal />
        </SceneContent>
    )
}
