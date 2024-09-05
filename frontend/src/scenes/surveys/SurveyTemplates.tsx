import './SurveyTemplates.scss'

import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { SceneExport } from 'scenes/sceneTypes'
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

    return (
        <>
            <PageHeader
                buttons={
                    <LemonButton type="primary" to={urls.survey('new')} data-attr="new-blank-survey">
                        Create blank survey
                    </LemonButton>
                }
            />
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
                                        appearance: { ...defaultSurveyAppearance, ...template.appearance },
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
