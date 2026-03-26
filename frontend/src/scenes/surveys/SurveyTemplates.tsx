import { LemonTag } from '@posthog/lemon-ui'

import { Survey, SurveyAppearance } from '~/types'

import { AbsoluteCornerBadge } from './components/AbsoluteCornerBadge'
import { SurveyTemplate, SurveyTemplateType, defaultSurveyAppearance } from './constants'
import { SurveyAppearancePreview } from './SurveyAppearancePreview'

interface TemplateCardProps {
    template: SurveyTemplate
    idx: number
    reportSurveyTemplateClicked: (templateType: SurveyTemplateType) => void
    surveyAppearance: SurveyAppearance
    handleTemplateClick: (template: SurveyTemplate) => void
    hideTag?: boolean
}

export function FeaturedTemplateCard({
    template,
    idx,
    handleTemplateClick,
    surveyAppearance,
}: TemplateCardProps): JSX.Element {
    return (
        <button
            className="relative flex w-full items-center justify-center gap-4 bg-bg-light border border-border rounded-lg hover:border-primary-3000-hover focus:border-primary-3000-hover focus:outline-none transition-colors h-full group p-4 cursor-pointer overflow-hidden"
            data-attr="survey-template"
            onClick={() => handleTemplateClick(template)}
        >
            <AbsoluteCornerBadge text="New template!" position="tl" />

            <div className="flex flex-col items-end">
                <h3 className="text-sm font-semibold text-default line-clamp-2 flex-1 mb-0">{template.templateType}</h3>
                <p className="text-sm text-secondary leading-relaxed line-clamp-3">{template.description}</p>
            </div>
            <div>
                <div className="transform scale-75 pointer-events-none">
                    <SurveyAppearancePreview
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

export function TemplateCard({
    template,
    idx,
    handleTemplateClick,
    surveyAppearance,
    hideTag,
}: TemplateCardProps): JSX.Element {
    return (
        <button
            className="relative flex flex-col bg-bg-light border border-border rounded-lg hover:border-primary-3000-hover focus:border-primary-3000-hover focus:outline-none transition-colors text-left h-full group p-4 cursor-pointer overflow-hidden"
            data-attr="survey-template"
            onClick={() => handleTemplateClick(template)}
        >
            {template.badge && <AbsoluteCornerBadge text={template.badge} position="br" />}

            <div>
                <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-default line-clamp-2 flex-1 mb-0">
                        {template.templateType}
                    </h3>
                    {!hideTag && (
                        <LemonTag type={template.tagType || 'default'} size="small" className="ml-2 flex-shrink-0">
                            {template.category || 'General'}
                        </LemonTag>
                    )}
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
