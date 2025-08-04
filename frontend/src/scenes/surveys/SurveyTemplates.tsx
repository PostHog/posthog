import './SurveyTemplates.scss'

import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Survey } from '~/types'

import { SurveyFeedbackButton } from 'scenes/surveys/components/SurveyFeedbackButton'
import { defaultSurveyAppearance, defaultSurveyTemplates, errorTrackingSurvey } from './constants'
import { SurveyAppearancePreview } from './SurveyAppearancePreview'
import { surveyLogic } from './surveyLogic'

export const scene: SceneExport = {
    component: SurveyTemplates,
    settingSectionId: 'environment-surveys',
}

export function SurveyTemplates(): JSX.Element {
    const { setSurveyTemplateValues } = useActions(surveyLogic({ id: 'new' }))
    const { reportSurveyTemplateClicked } = useActions(eventUsageLogic)
    const { currentTeam } = useValues(teamLogic)
    const surveyAppearance = {
        ...currentTeam?.survey_config?.appearance,
    }

    const templates = [...defaultSurveyTemplates, errorTrackingSurvey]

    return (
        <>
            <PageHeader
                buttons={
                    <>
                        <SurveyFeedbackButton />
                        <LemonButton type="primary" to={urls.survey('new')} data-attr="new-blank-survey">
                            Create blank survey
                        </LemonButton>
                    </>
                }
            />
            <div className="flex flex-row flex-wrap gap-8 mt-8">
                {templates.map((template, idx) => {
                    return (
                        <div className="flex flex-col items-center" key={idx}>
                            <span className="text-md">
                                <b>{template.templateType}</b>
                            </span>
                            <span className="flex flex-wrap text-xs text-secondary max-w-80 font-medium mb-3">
                                {template.description}
                            </span>
                            <div
                                className="SurveyTemplateContainer"
                                tabIndex={idx + 1}
                                data-attr="survey-template"
                                onClick={() => {
                                    setSurveyTemplateValues({
                                        name: template.templateType,
                                        questions: template.questions ?? [],
                                        appearance: {
                                            ...defaultSurveyAppearance,
                                            ...template.appearance,
                                            ...surveyAppearance,
                                        },
                                        conditions: template.conditions ?? null,
                                    })
                                    reportSurveyTemplateClicked(template.templateType)
                                }}
                                onKeyDown={(event) => {
                                    if (event.key === 'Enter') {
                                        event.currentTarget.click()
                                    }
                                }}
                            >
                                <div className="SurveyTemplate">
                                    <SurveyAppearancePreview
                                        key={idx}
                                        survey={
                                            {
                                                id: `templateMock-${idx}`,
                                                questions: template.questions,
                                                appearance: {
                                                    ...defaultSurveyAppearance,
                                                    whiteLabel: true,
                                                    ...template.appearance,
                                                    ...surveyAppearance,
                                                    disabledButtonOpacity: '1',
                                                    maxWidth: '300px',
                                                },
                                            } as Survey
                                        }
                                        previewPageIndex={0}
                                    />
                                </div>
                            </div>
                        </div>
                    )
                })}
            </div>
        </>
    )
}
