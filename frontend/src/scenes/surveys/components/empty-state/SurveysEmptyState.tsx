import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useState } from 'react'
import { toast } from 'react-toastify'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import MaxTool from 'scenes/max/MaxTool'
import { QuickSurveyModal } from 'scenes/surveys/QuickSurveyModal'
import { captureMaxAISurveyCreationException } from 'scenes/surveys/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { SidePanelTab, Survey } from '~/types'

import { FeaturedTemplateCard, TemplateCard } from '../../SurveyTemplates'
import {
    QuickSurveyFromTemplate,
    SURVEY_CREATED_SOURCE,
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
    const { createSurveyFromTemplate, addProductIntent } = useActions(surveysLogic)
    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { openSidePanel } = useActions(sidePanelLogic)
    const {
        data: { surveysCount },
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
                                <MaxTool
                                    identifier="create_survey"
                                    initialMaxPrompt="Create a survey to collect "
                                    suggestions={[
                                        'Create an NPS survey for customers who completed checkout',
                                        'Create a feedback survey asking about our new dashboard',
                                    ]}
                                    context={{}}
                                    callback={(toolOutput: {
                                        survey_id?: string
                                        error?: string
                                        error_message?: string
                                    }) => {
                                        addProductIntent({
                                            product_type: ProductKey.SURVEYS,
                                            intent_context: ProductIntentContext.SURVEY_CREATED,
                                            metadata: {
                                                survey_id: toolOutput.survey_id,
                                                source: SURVEY_CREATED_SOURCE.SURVEY_EMPTY_STATE,
                                                created_successfully: !toolOutput?.error,
                                            },
                                        })

                                        if (toolOutput?.error || !toolOutput?.survey_id) {
                                            return captureMaxAISurveyCreationException(
                                                toolOutput.error,
                                                SURVEY_CREATED_SOURCE.SURVEY_EMPTY_STATE
                                            )
                                        }

                                        router.actions.push(urls.survey(toolOutput.survey_id))
                                    }}
                                >
                                    <LemonButton
                                        type="primary"
                                        icon={<IconSparkles />}
                                        onClick={() => openSidePanel(SidePanelTab.Max, 'Create a survey to collect ')}
                                    >
                                        Create your own custom survey with PostHog AI
                                    </LemonButton>
                                </MaxTool>
                            )}
                            <LemonButton type="secondary" onClick={() => router.actions.push(urls.surveyTemplates())}>
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
