import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { FEATURE_FLAGS } from 'lib/constants'
import { ProductIntentContext } from 'lib/utils/product-intents'
import posthog from 'posthog-js'
import MaxTool from 'scenes/max/MaxTool'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { ProductKey, SidePanelTab } from '~/types'
import { defaultSurveyTemplates, SURVEY_CREATED_SOURCE, SurveyTemplateType } from '../../constants'
import { surveysLogic } from '../../surveysLogic'
import { TemplateCard } from '../../SurveyTemplates'

interface Props {
    numOfSurveys: number
}

export function SurveysEmptyState({ numOfSurveys }: Props): JSX.Element {
    const { createSurveyFromTemplate, addProductIntent } = useActions(surveysLogic)
    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { openSidePanel } = useActions(sidePanelLogic)

    // Get the three priority templates
    const priorityTemplates = defaultSurveyTemplates.filter((template) =>
        [SurveyTemplateType.OpenFeedback, SurveyTemplateType.NPS, SurveyTemplateType.CSAT].includes(
            template.templateType
        )
    )

    const surveyAppearance = {
        ...currentTeam?.survey_config?.appearance,
    }

    const handleCreateSurveyFromTemplate = async (templateType: SurveyTemplateType): Promise<void> => {
        try {
            await createSurveyFromTemplate(templateType)
        } catch (error) {
            console.error('Failed to create survey from template:', error)
        }
    }

    return (
        <>
            <FlaggedFeature flag={FEATURE_FLAGS.SURVEY_EMPTY_STATE_V2} match="test">
                <div className="border-2 border-dashed border-primary w-full p-4 rounded">
                    <div className="flex items-center justify-center">
                        <div className="space-y-6">
                            <div>
                                <h2 className="mb-0">Create your first survey</h2>
                                <p className="mb-0">
                                    Choose from our most popular templates to get started quickly, or create your own
                                    from scratch.
                                </p>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                {priorityTemplates.map((template, idx) => (
                                    <TemplateCard
                                        key={template.templateType}
                                        template={template}
                                        idx={idx}
                                        setSurveyTemplateValues={() => {}} // Not used in this context
                                        reportSurveyTemplateClicked={() => {}} // Not used in this context
                                        surveyAppearance={surveyAppearance}
                                        handleTemplateClick={() =>
                                            handleCreateSurveyFromTemplate(template.templateType)
                                        }
                                    />
                                ))}
                            </div>

                            <div className="flex items-center gap-x-4 gap-y-2 flex-wrap">
                                {user?.uuid && (
                                    <MaxTool
                                        name="create_survey"
                                        description="Max can create surveys to collect qualitative feedback from your users."
                                        displayName="Create with Max AI"
                                        initialMaxPrompt="Create a survey to collect "
                                        suggestions={[
                                            'Create an NPS survey for customers who completed checkout',
                                            'Create a feedback survey asking about our new dashboard',
                                        ]}
                                        context={{ user_id: user.uuid }}
                                        callback={(toolOutput: { survey_id?: string; error?: string }) => {
                                            addProductIntent({
                                                product_type: ProductKey.SURVEYS,
                                                intent_context: ProductIntentContext.SURVEY_CREATED,
                                                metadata: {
                                                    survey_id: toolOutput.survey_id,
                                                    source: SURVEY_CREATED_SOURCE.MAX_AI,
                                                    created_successfully: !toolOutput?.error,
                                                },
                                            })

                                            if (toolOutput?.error || !toolOutput?.survey_id) {
                                                posthog.captureException('survey-creation-failed', {
                                                    error: toolOutput.error,
                                                })
                                                return
                                            }

                                            router.actions.push(urls.survey(toolOutput.survey_id))
                                        }}
                                    >
                                        <LemonButton
                                            type="primary"
                                            icon={<IconSparkles />}
                                            onClick={() =>
                                                openSidePanel(SidePanelTab.Max, 'Create a survey to collect ')
                                            }
                                        >
                                            Create your own custom survey with Max
                                        </LemonButton>
                                    </MaxTool>
                                )}
                                <LemonButton
                                    type="secondary"
                                    onClick={() => router.actions.push(urls.surveyTemplates())}
                                >
                                    See all other templates
                                </LemonButton>
                            </div>
                        </div>
                    </div>
                </div>
            </FlaggedFeature>
            <FlaggedFeature flag={FEATURE_FLAGS.SURVEY_EMPTY_STATE_V2} match="control">
                <ProductIntroduction
                    productName="Surveys"
                    thingName="survey"
                    description="Use surveys to gather qualitative feedback from your users on new or existing features."
                    action={() => router.actions.push(urls.surveyTemplates())}
                    isEmpty={numOfSurveys === 0}
                    productKey={ProductKey.SURVEYS}
                />
            </FlaggedFeature>
        </>
    )
}
