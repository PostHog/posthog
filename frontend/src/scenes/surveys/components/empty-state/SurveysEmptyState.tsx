import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { QuickSurveyModal } from 'scenes/surveys/QuickSurveyModal'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Survey } from '~/types'

import {
    QuickSurveyFromTemplate,
    SURVEY_CREATED_SOURCE,
    SurveyTemplate,
    SurveyTemplateType,
    defaultSurveyAppearance,
    defaultSurveyTemplates,
} from '../../constants'
import { FeaturedTemplateCard, TemplateCard } from '../../SurveyTemplates'

export function SurveysEmptyState(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { reportSurveyTemplateClicked } = useActions(eventUsageLogic)

    const [quickModalOpen, setQuickModalOpen] = useState<boolean>(false)
    const [quickSurveyContext, setQuickSurveyContext] = useState<QuickSurveyFromTemplate | undefined>(undefined)

    const templateToSurvey = (template: SurveyTemplate): Partial<Survey> & SurveyTemplate => {
        return {
            ...template,
            name: template.templateType,
            appearance: {
                ...template.appearance,
                ...currentTeam?.survey_config?.appearance,
            },
        }
    }

    // Get the three priority templates - most popular based on the Surveys dashboard
    const priorityTemplates = defaultSurveyTemplates
        .filter((template) =>
            [SurveyTemplateType.OpenFeedback, SurveyTemplateType.NPS, SurveyTemplateType.CSAT].includes(
                template.templateType
            )
        )
        .map(templateToSurvey)

    const featuredTemplate = defaultSurveyTemplates
        .filter((t) => t.featured)
        .slice(0, 1)
        .map(templateToSurvey)
        .at(0)

    const handleTemplateClick = (survey: SurveyTemplate): void => {
        reportSurveyTemplateClicked(survey.templateType, SURVEY_CREATED_SOURCE.SURVEY_EMPTY_STATE)
        if (survey.quickSurvey) {
            setQuickSurveyContext(survey.quickSurvey)
            setQuickModalOpen(true)
        } else {
            router.actions.push(urls.surveyWizard('new', survey.templateType))
        }
    }

    return (
        <>
            <div className="border-2 border-dashed border-primary w-full p-4 rounded">
                <div className="flex items-center justify-center">
                    <div className="space-y-6">
                        <div>
                            <h2 className="mb-0">Create your first survey</h2>
                            <p className="mb-0">
                                Choose from our most popular templates to get started quickly, or create your own from
                                scratch.
                            </p>
                        </div>

                        {featuredTemplate && (
                            <div>
                                <FeaturedTemplateCard
                                    template={featuredTemplate}
                                    idx={0}
                                    reportSurveyTemplateClicked={() => {}}
                                    surveyAppearance={featuredTemplate.appearance ?? {}}
                                    handleTemplateClick={handleTemplateClick}
                                />
                            </div>
                        )}
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            {priorityTemplates.map((template, idx) => (
                                <TemplateCard
                                    key={template.templateType}
                                    template={template}
                                    idx={idx + 1}
                                    reportSurveyTemplateClicked={() => {}}
                                    surveyAppearance={template.appearance ?? defaultSurveyAppearance}
                                    handleTemplateClick={handleTemplateClick}
                                />
                            ))}
                        </div>

                        <div className="flex items-center gap-x-4 gap-y-2 flex-wrap">
                            <LemonButton type="secondary" onClick={() => router.actions.push(urls.surveyWizard())}>
                                See all other templates
                            </LemonButton>
                        </div>
                    </div>
                </div>
            </div>
            <QuickSurveyModal
                context={quickSurveyContext?.context}
                isOpen={quickModalOpen}
                onCancel={() => setQuickModalOpen(false)}
                modalTitle={quickSurveyContext?.modalTitle}
                info={quickSurveyContext?.info}
            />
        </>
    )
}
