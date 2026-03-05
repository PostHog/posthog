import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef, useState } from 'react'

import { IconArrowRight, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { MicrophoneHog } from 'lib/components/hedgehogs'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { QuickSurveyModal } from 'scenes/surveys/QuickSurveyModal'
import { FeaturedTemplateCard, TemplateCard } from 'scenes/surveys/SurveyTemplates'
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
import { surveysLogic } from '../../surveysLogic'

const TEMPLATE_TYPES = [SurveyTemplateType.NPS, SurveyTemplateType.CSAT, SurveyTemplateType.PMF]

function SurveysEmptyStateContent(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { reportSurveyTemplateClicked } = useActions(eventUsageLogic)
    const { handleMaxSurveyCreated } = useActions(surveysLogic)

    const [quickModalOpen, setQuickModalOpen] = useState<boolean>(false)
    const [quickSurveyContext, setQuickSurveyContext] = useState<QuickSurveyFromTemplate | undefined>(undefined)

    const { openMax } = useMaxTool({
        identifier: 'create_survey',
        initialMaxPrompt: `Create a survey to collect `,
        callback: (toolOutput) => handleMaxSurveyCreated(toolOutput, SURVEY_CREATED_SOURCE.SURVEY_EMPTY_STATE),
    })

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
                            <LemonButton type="primary" icon={<IconSparkles />} onClick={() => openMax?.()}>
                                Create your own custom survey with PostHog AI
                            </LemonButton>
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

function SurveysEmptyStateAIContent(): JSX.Element {
    const [prompt, setPrompt] = useState('')

    const { reportSurveyTemplateClicked, reportSurveyAiPromptSubmitted } = useActions(eventUsageLogic)
    const { handleMaxSurveyCreated } = useActions(surveysLogic)
    const { openMax } = useMaxTool({
        identifier: 'create_survey',
        initialMaxPrompt: `!${prompt.trim()}`,
        callback: (toolOutput) => handleMaxSurveyCreated(toolOutput, SURVEY_CREATED_SOURCE.SURVEY_EMPTY_STATE),
    })
    const textAreaRef = useRef<HTMLTextAreaElement>(null)

    const handleSubmit = (): void => {
        if (prompt.trim()) {
            reportSurveyAiPromptSubmitted(SURVEY_CREATED_SOURCE.SURVEY_EMPTY_STATE)
            openMax?.()
            setPrompt('')
        }
    }

    const templates = defaultSurveyTemplates.filter((t) => TEMPLATE_TYPES.includes(t.templateType))

    const handleTemplateClick = (survey: SurveyTemplate): void => {
        reportSurveyTemplateClicked(survey.templateType, 'empty_state')
        router.actions.push(urls.surveyWizard('new', survey.templateType))
    }

    return (
        <div className="w-full max-w-5xl mx-auto py-10 px-4">
            <div className="text-center mb-6">
                <MicrophoneHog className="size-20 mx-auto -mb-1" />
                <h2 className="text-2xl font-bold mb-1">Create your first survey</h2>
                <p className="text-secondary text-sm mb-0">
                    Tell AI what you want to learn from your users, or pick a template below.
                </p>
            </div>

            <div className="rounded-xl border-2 border-[var(--color-ai)] mb-8">
                <label
                    htmlFor="survey-ai-prompt"
                    className="flex flex-col cursor-text"
                    onClick={() => textAreaRef.current?.focus()}
                >
                    <LemonTextArea
                        id="survey-ai-prompt"
                        ref={textAreaRef}
                        value={prompt}
                        onChange={setPrompt}
                        onPressEnter={handleSubmit}
                        placeholder="e.g., Create an NPS survey for users who completed onboarding, shown on the dashboard page"
                        minRows={2}
                        maxRows={5}
                        className="!border-none !bg-transparent !shadow-none !rounded-none px-4 pt-4 pb-2 resize-none text-sm"
                        hideFocus
                        data-attr="survey-ai-prompt-input"
                    />
                    <div className="flex items-center justify-between px-4 pb-3">
                        <div className="flex items-center gap-1.5 text-xs text-tertiary">
                            <IconSparkles className="text-ai size-3.5" />
                            <span>PostHog AI</span>
                        </div>
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconArrowRight />}
                            onClick={handleSubmit}
                            disabledReason={!prompt.trim() ? 'Describe the survey you want' : undefined}
                            data-attr="survey-ai-prompt-submit"
                        >
                            Create with AI
                        </LemonButton>
                    </div>
                </label>
            </div>

            <div className="flex items-center gap-4 mb-6">
                <div className="flex-1 border-t border-primary" />
                <span className="text-xs text-tertiary uppercase tracking-wide">or start with a template</span>
                <div className="flex-1 border-t border-primary" />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
                {templates.map((template, idx) => (
                    <TemplateCard
                        key={template.templateType}
                        template={template}
                        idx={idx + 1}
                        reportSurveyTemplateClicked={() => {}}
                        surveyAppearance={template.appearance ?? defaultSurveyAppearance}
                        handleTemplateClick={handleTemplateClick}
                        hideTag={true}
                    />
                ))}
            </div>

            <div className="flex items-center justify-center text-center">
                <LemonButton type="secondary" size="small" onClick={() => router.actions.push(urls.surveyWizard())}>
                    See more templates
                </LemonButton>
            </div>
        </div>
    )
}

export function SurveysEmptyState(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { reportSurveyEmptyStateViewed } = useActions(eventUsageLogic)

    useEffect(() => {
        reportSurveyEmptyStateViewed()
    }, [reportSurveyEmptyStateViewed])

    if (featureFlags[FEATURE_FLAGS.SURVEYS_AI_FIRST_EMPTY_STATE] === 'test') {
        return <SurveysEmptyStateAIContent />
    }

    return <SurveysEmptyStateContent />
}
