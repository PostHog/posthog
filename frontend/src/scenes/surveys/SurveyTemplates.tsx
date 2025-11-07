import { useActions, useValues } from 'kea'

import { LemonTag, Link } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { Survey, SurveyAppearance } from '~/types'

import { SurveyAppearancePreview } from './SurveyAppearancePreview'
import {
    NewSurvey,
    SurveyTemplate,
    SurveyTemplateType,
    defaultSurveyAppearance,
    defaultSurveyTemplates as templates,
} from './constants'
import { surveyLogic } from './surveyLogic'

export const scene: SceneExport = {
    component: SurveyTemplates,
    settingSectionId: 'environment-surveys',
}

interface TemplateCardProps {
    template: SurveyTemplate
    idx: number
    setSurveyTemplateValues: (values: Partial<NewSurvey>) => void
    reportSurveyTemplateClicked: (templateType: SurveyTemplateType) => void
    surveyAppearance: SurveyAppearance
    handleTemplateClick: (template: SurveyTemplate) => void
    isMostPopular?: boolean
}

export function TemplateCard({
    template,
    idx,
    handleTemplateClick,
    surveyAppearance,
    isMostPopular,
}: TemplateCardProps): JSX.Element {
    return (
        <button
            className="relative flex flex-col bg-bg-light border border-border rounded-lg hover:border-primary-3000-hover focus:border-primary-3000-hover focus:outline-none transition-colors text-left h-full group p-4 cursor-pointer overflow-hidden"
            data-attr="survey-template"
            onClick={() => handleTemplateClick(template)}
        >
            {isMostPopular && (
                <div className="absolute bottom-0 right-0 z-10">
                    <div className="relative">
                        <div className="bg-primary-3000/85 text-white text-xs font-semibold px-3 py-1 rounded-tl-lg rounded-br-lg shadow-md">
                            Most Popular
                        </div>
                        <div className="absolute bottom-full right-0 w-0 h-0 border-r-[8px] border-r-transparent border-b-[6px] border-b-primary-3000 opacity-60" />
                    </div>
                </div>
            )}
            <div>
                <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-default line-clamp-2 flex-1 mb-0">
                        {template.templateType}
                    </h3>
                    <LemonTag type={template.tagType || 'default'} size="small" className="ml-2 flex-shrink-0">
                        {template.category || 'General'}
                    </LemonTag>
                </div>
                <p className="text-sm text-secondary leading-relaxed line-clamp-3">{template.description}</p>
            </div>

            <div className="flex-1 flex items-center justify-center">
                <div className="transform scale-75 pointer-events-none">
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
                                    maxWidth: '320px',
                                },
                            } as Survey
                        }
                        previewPageIndex={0}
                    />
                </div>
            </div>
        </button>
    )
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
            <div className="mb-2 -ml-[var(--button-padding-x-lg)]">
                <SceneBreadcrumbBackButton
                    forceBackTo={{
                        key: Scene.Surveys,
                        name: 'Surveys',
                        path: urls.surveys(),
                    }}
                />
            </div>
            <div className="space-y-4">
                <p className="text-center text-base">
                    Choose a template based on your goal, or{' '}
                    <Link to={urls.survey('new')} className="text-primary-3000" data-attr="new-blank-survey">
                        start from scratch with a blank survey
                    </Link>
                    .
                </p>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4">
                    {templates.map((template, idx) => (
                        <TemplateCard
                            key={idx}
                            template={template}
                            idx={idx}
                            setSurveyTemplateValues={setSurveyTemplateValues}
                            reportSurveyTemplateClicked={reportSurveyTemplateClicked}
                            surveyAppearance={surveyAppearance}
                            isMostPopular={template.templateType === SurveyTemplateType.OpenFeedback}
                            handleTemplateClick={(template) => {
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
                        />
                    ))}
                </div>
            </div>
        </>
    )
}
