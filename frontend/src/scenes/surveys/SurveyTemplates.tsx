import './SurveyTemplates.scss'

import { LemonBadge, LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Survey } from '~/types'

import { defaultSurveyAppearance, defaultSurveyTemplates } from './constants'
import { SurveyAppearancePreview } from './SurveyAppearancePreview'
import { surveyLogic } from './surveyLogic'

export const scene: SceneExport = {
    component: SurveyTemplates,
}

export function SurveyTemplates(): JSX.Element {
    const { setSurveyTemplateValues } = useActions(surveyLogic({ id: 'new' }))
    const { reportSurveyTemplateClicked } = useActions(eventUsageLogic)
    const { currentTeam } = useValues(teamLogic)
    const surveyAppearance = {
        ...currentTeam?.survey_config?.appearance,
    }

    return (
        <>
            <PageHeader
                buttons={
                    <LemonButton type="primary" to={urls.survey('new')} data-attr="new-blank-survey">
                        Create blank survey
                    </LemonButton>
                }
            />
            {currentTeam?.survey_config?.templates && (
                <div className="flex items-center min-h-6">
                    <div className="mr-1">Custom</div>
                    <LemonBadge.Number
                        count={Object.keys(defaultSurveyTemplates).length}
                        size="medium"
                        maxDigits={Infinity}
                    />
                </div>
            )}
            <LemonDivider dashed={true} />
            <div className="flex items-center min-h-6">
                <div className="mr-1">Default</div>
                <LemonBadge.Number
                    count={Object.keys(defaultSurveyTemplates).length}
                    size="medium"
                    maxDigits={Infinity}
                />
            </div>
            <LemonDivider />
            <div className="flex flex-row flex-wrap gap-8 mt-8">
                {defaultSurveyTemplates.map((template, idx) => {
                    return (
                        <div className="flex flex-col items-center" key={idx}>
                            <span className="text-md">
                                <b>{template.templateType}</b>
                            </span>
                            <span className="flex flex-wrap text-xs text-muted max-w-80 font-medium mb-3">
                                {template.description}
                            </span>
                            <div
                                className="SurveyTemplateContainer"
                                tabIndex={idx + 1}
                                data-attr="survey-template"
                                onClick={() => {
                                    setSurveyTemplateValues({
                                        name: template.templateType,
                                        questions: template.questions,
                                        appearance: {
                                            ...defaultSurveyAppearance,
                                            ...template.appearance,
                                            ...surveyAppearance,
                                        },
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
                                        surveyAppearance={surveyAppearance}
                                        survey={
                                            {
                                                id: `templateMock-${idx}`,
                                                questions: template.questions,
                                                appearance: {
                                                    ...defaultSurveyAppearance,
                                                    whiteLabel: true,
                                                    ...template.appearance,
                                                    ...surveyAppearance,
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
