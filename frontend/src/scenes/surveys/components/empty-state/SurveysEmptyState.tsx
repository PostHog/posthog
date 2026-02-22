import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useState } from 'react'
import { toast } from 'react-toastify'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useOpenAi } from 'scenes/max/useOpenAi'
import { QuickSurveyModal } from 'scenes/surveys/QuickSurveyModal'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { Survey } from '~/types'

import { FeaturedTemplateCard, TemplateCard } from '../../SurveyTemplates'
import {
    QuickSurveyFromTemplate,
    SurveyTemplate,
    SurveyTemplateType,
    defaultSurveyAppearance,
    defaultSurveyTemplates,
} from '../../constants'
import { surveysLogic } from '../../surveysLogic'

interface Props {
    numOfSurveys: number
}

export function SurveysEmptyState({ numOfSurveys }: Props): JSX.Element {
    const { createSurveyFromTemplate } = useActions(surveysLogic)
    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { openAi } = useOpenAi()
    const {
        data: { surveysCount },
        guidedEditorEnabled,
    } = useValues(surveysLogic)

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

    const handleTemplateClick = async (survey: SurveyTemplate): Promise<void> => {
        if (guidedEditorEnabled) {
            router.actions.push(urls.surveyWizard() + `?template=${encodeURIComponent(survey.templateType)}`)
            return
        }

        if (survey.quickSurvey) {
            setQuickSurveyContext(survey.quickSurvey)
            setQuickModalOpen(true)
        } else {
            try {
                await createSurveyFromTemplate(survey)
            } catch (error) {
                posthog.captureException(error, {
                    action: 'survey-creation-from-template-failed',
                })
                toast.error('Error while creating survey from template. Please try again.')
            }
        }
    }

    return (
        <>
            <div className="border-2 border-dashed border-primary w-full p-4 rounded">
                <div className="flex items-center justify-center">
                    <div className="space-y-6">
                        <div>
                            <h2 className="mb-0">
                                {surveysCount > 0 ? 'Create your next survey' : 'Create your first survey'}
                            </h2>
                            <p className="mb-0">
                                Choose from our most popular templates to get started quickly, or create your own from
                                scratch.
                            </p>
                            {numOfSurveys > 0 && (
                                <p className="mb-0">
                                    Your team is already using surveys. You can take a look at what they're doing, or
                                    get started yourself.
                                </p>
                            )}
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
                            {user?.uuid && (
                                <LemonButton
                                    type="primary"
                                    icon={<IconSparkles />}
                                    onClick={() => openAi('Create a survey to collect ')}
                                >
                                    Create your own custom survey with PostHog AI
                                </LemonButton>
                            )}
                            <LemonButton
                                type="secondary"
                                onClick={() =>
                                    router.actions.push(
                                        guidedEditorEnabled ? urls.surveyWizard() : urls.surveyTemplates()
                                    )
                                }
                            >
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
