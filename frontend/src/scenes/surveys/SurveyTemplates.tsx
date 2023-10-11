import { SceneExport } from 'scenes/sceneTypes'
import { SurveyAppearance } from './SurveyAppearance'
import { defaultSurveyTemplates } from './constants'
import { SurveyQuestion } from '~/types'
import './SurveyTemplates.scss'
import { useActions } from 'kea'
import { surveyTemplatesLogic } from './surveyTemplatesLogic'

export const scene: SceneExport = {
    component: SurveyTemplates,
}

export function SurveyTemplates(): JSX.Element {
    const { openSurveyTemplate } = useActions(surveyTemplatesLogic)

    return (
        <>
            <div className="flex flex-row flex-wrap gap-6 ml-8 mt-6">
                {defaultSurveyTemplates.map((template, idx) => {
                    return (
                        <div
                            className="flex flex-col items-center max-w-100"
                            key={idx}
                            onClick={(template) => openSurveyTemplate(template)}
                        >
                            <span className="mb-2">
                                <b>{template.type}</b>
                            </span>
                            <div className="SurveyTemplateContainer">
                                <div className="SurveyTemplate">
                                    <SurveyAppearance
                                        key={idx}
                                        type={template.questions[0].type}
                                        question={template.questions[0].question}
                                        appearance={{}}
                                        surveyQuestionItem={template.questions[0] as SurveyQuestion}
                                        onAppearanceChange={() => {}}
                                        readOnly
                                    />
                                </div>
                            </div>
                            <span className="flex flex-wrap text-xs text-muted max-w-80 font-medium mt-3">
                                {template.description}
                            </span>
                        </div>
                    )
                })}
            </div>
        </>
    )
}
