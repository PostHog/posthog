import './SurveyTemplates.scss'

import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SurveyQuestion } from '~/types'

import { defaultSurveyAppearance, defaultSurveyTemplates } from './constants'
import { SurveyAppearance } from './SurveyAppearance'
import { surveyLogic } from './surveyLogic'

export const scene: SceneExport = {
    component: SurveyTemplates,
}

export function SurveyTemplates(): JSX.Element {
    const { setSurveyTemplateValues } = useActions(surveyLogic({ id: 'new' }))
    const { reportSurveyTemplateClicked } = useActions(eventUsageLogic)

    return (
        <>
            <PageHeader
                title={'New survey'}
                buttons={
                    <LemonButton type="primary" to={urls.survey('new')} data-attr="new-blank-survey">
                        Create blank survey
                    </LemonButton>
                }
            />
            <div className="flex flex-row flex-wrap gap-8 mt-8">
                {defaultSurveyTemplates.map((template, idx) => {
                    return (
                        <div
                            className="flex flex-col items-center"
                            data-attr="survey-template"
                            key={idx}
                            onClick={() => {
                                setSurveyTemplateValues({
                                    name: template.type,
                                    questions: template.questions,
                                    appearance: { ...defaultSurveyAppearance, ...template.appearance },
                                })
                                reportSurveyTemplateClicked(template.type)
                            }}
                        >
                            <span className="text-md">
                                <b>{template.type}</b>
                            </span>
                            <span className="flex flex-wrap text-xs text-muted max-w-80 font-medium mb-3">
                                {template.description}
                            </span>
                            <div className="SurveyTemplateContainer">
                                <div className="SurveyTemplate">
                                    <SurveyAppearance
                                        key={idx}
                                        type={template.questions[0].type}
                                        appearance={{
                                            ...defaultSurveyAppearance,
                                            whiteLabel: true,
                                            ...template.appearance,
                                        }}
                                        surveyQuestionItem={template.questions[0] as SurveyQuestion}
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
