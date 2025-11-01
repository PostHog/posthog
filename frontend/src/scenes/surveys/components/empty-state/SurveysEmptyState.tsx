import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { toast } from 'react-toastify'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ProductIntentContext } from 'lib/utils/product-intents'
import MaxTool from 'scenes/max/MaxTool'
import { captureMaxAISurveyCreationException } from 'scenes/surveys/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { ProductKey, SidePanelTab } from '~/types'

import { TemplateCard } from '../../SurveyTemplates'
import { SURVEY_CREATED_SOURCE, SurveyTemplate, SurveyTemplateType, defaultSurveyTemplates } from '../../constants'
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

    // Get the three priority templates - most popular based on the Surveys dashboard
    const priorityTemplates = defaultSurveyTemplates
        .filter((template) =>
            [SurveyTemplateType.OpenFeedback, SurveyTemplateType.NPS, SurveyTemplateType.CSAT].includes(
                template.templateType
            )
        )
        .map((template) => ({
            ...template,
            name: template.templateType,
            appearance: {
                ...template.appearance,
                ...currentTeam?.survey_config?.appearance,
            },
        }))

    const handleCreateSurveyFromTemplate = async (survey: SurveyTemplate): Promise<void> => {
        try {
            await createSurveyFromTemplate(survey)
        } catch (error) {
            posthog.captureException(error, {
                action: 'survey-creation-from-template-failed',
            })
            toast.error('Error while creating survey from template. Please try again.')
        }
    }

    return (
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
                                Your team is already using surveys. You can take a look at what they're doing, or get
                                started yourself.
                            </p>
                        )}
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        {priorityTemplates.map((template, idx) => (
                            <TemplateCard
                                key={template.templateType}
                                template={template}
                                idx={idx}
                                setSurveyTemplateValues={() => {}} // Not used in this context
                                reportSurveyTemplateClicked={() => {}} // Not used in this context
                                surveyAppearance={template.appearance}
                                handleTemplateClick={() => handleCreateSurveyFromTemplate(template)}
                                isMostPopular={template.templateType === SurveyTemplateType.OpenFeedback}
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
                                context={{ user_id: user.uuid }}
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
                                    Create your own custom survey with Intelligence
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
    )
}
