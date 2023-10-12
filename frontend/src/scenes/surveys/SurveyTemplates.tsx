import { SceneExport } from 'scenes/sceneTypes'
import { SurveyAppearance } from './SurveyAppearance'
import { defaultSurveyTemplates } from './constants'
import { SurveyQuestion } from '~/types'
import './SurveyTemplates.scss'
import { useActions } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { surveyLogic } from './surveyLogic'

export const scene: SceneExport = {
    component: SurveyTemplates,
}

export function SurveyTemplates(): JSX.Element {
    const { setSurveyTemplateValues } = useActions(surveyLogic({ id: 'new' }))

    return (
        <>
            <PageHeader
                title={'New survey'}
                buttons={
                    <LemonButton type="primary" to={urls.survey('new')} data-attr="new-survey">
                        Create blank survey
                    </LemonButton>
                }
            />
            <div className="flex flex-row flex-wrap gap-10 ml-8 mt-8">
                {defaultSurveyTemplates.map((template, idx) => {
                    return (
                        <div
                            className="flex flex-col items-center"
                            key={idx}
                            onClick={() =>
                                setSurveyTemplateValues({ name: template.type, questions: template.questions })
                            }
                        >
                            <span className="mb-2 text-md">
                                <b>{template.type}</b>
                            </span>
                            <div className="SurveyTemplateContainer">
                                <div className="SurveyTemplate">
                                    <SurveyAppearance
                                        key={idx}
                                        type={template.questions[0].type}
                                        question={template.questions[0].question}
                                        appearance={{ whiteLabel: true, ...template.appearance }}
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
