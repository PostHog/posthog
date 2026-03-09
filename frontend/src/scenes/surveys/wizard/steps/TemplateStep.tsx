import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import {
    IconArrowRight,
    IconChevronDown,
    IconChevronRight,
    IconComment,
    IconFlask,
    IconGraph,
    IconHandwave,
    IconMegaphone,
    IconPeople,
    IconPulse,
    IconSparkles,
    IconTarget,
    IconThumbsUp,
    IconTrending,
    IconWarning,
} from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useMaxTool } from 'scenes/max/useMaxTool'

import { SURVEY_CREATED_SOURCE, SurveyTemplate, SurveyTemplateType } from '../../constants'
import { surveysLogic } from '../../surveysLogic'
import { surveyWizardLogic } from '../surveyWizardLogic'

const TEMPLATE_ICONS: Partial<Record<SurveyTemplateType, React.ComponentType<{ className?: string }>>> = {
    [SurveyTemplateType.NPS]: IconGraph,
    [SurveyTemplateType.CSAT]: IconThumbsUp,
    [SurveyTemplateType.PMF]: IconTarget,
    [SurveyTemplateType.OpenFeedback]: IconComment,
    [SurveyTemplateType.CES]: IconPulse,
    [SurveyTemplateType.CCR]: IconPeople,
    [SurveyTemplateType.Interview]: IconPeople,
    [SurveyTemplateType.ErrorTracking]: IconWarning,
    [SurveyTemplateType.TrafficAttribution]: IconTrending,
    [SurveyTemplateType.FeatureRequest]: IconSparkles,
    [SurveyTemplateType.OnboardingFeedback]: IconHandwave,
    [SurveyTemplateType.BetaFeedback]: IconFlask,
    [SurveyTemplateType.Announcement]: IconMegaphone,
}

interface TemplateCardProps {
    template: SurveyTemplate
    onClick: () => void
    featured?: boolean
}

function TemplateCard({ template, onClick, featured }: TemplateCardProps): JSX.Element {
    const Icon = TEMPLATE_ICONS[template.templateType] || IconComment

    return (
        <button
            type="button"
            onClick={onClick}
            className={clsx(
                'group relative text-left rounded-lg border border-border bg-bg-light transition-all cursor-pointer',
                'hover:border-border-bold hover:shadow-sm',
                'focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2',
                featured ? 'p-5' : 'p-4'
            )}
        >
            {template.badge && (
                <span className="absolute top-4 right-4 text-xs font-medium text-muted">{template.badge}</span>
            )}
            <div className="flex flex-col gap-3">
                <Icon className={clsx('transition-colors group-hover:text-link', featured ? 'text-2xl' : 'text-xl')} />
                <div>
                    <h3
                        className={clsx(
                            'font-semibold mb-1 transition-colors group-hover:text-link',
                            featured ? 'text-base' : 'text-sm'
                        )}
                    >
                        {template.templateType}
                    </h3>
                    <p className={clsx('text-secondary leading-snug', featured ? 'text-sm' : 'text-xs')}>
                        {template.description}
                    </p>
                </div>
            </div>
        </button>
    )
}

export function TemplateStep({ handleCustomizeMore }: { handleCustomizeMore: () => void }): JSX.Element {
    const { coreTemplates, otherTemplates } = useValues(surveyWizardLogic)
    const { selectTemplate } = useActions(surveyWizardLogic)
    const { reportSurveyAiPromptSubmitted } = useActions(eventUsageLogic)
    const { handleMaxSurveyCreated } = useActions(surveysLogic)
    const [showOthers, setShowOthers] = useState(false)
    const [prompt, setPrompt] = useState('')
    const textAreaRef = useRef<HTMLTextAreaElement>(null)
    const { openMax } = useMaxTool({
        identifier: 'create_survey',
        initialMaxPrompt: `!${prompt.trim()}`,
        callback: (toolOutput) => handleMaxSurveyCreated(toolOutput, SURVEY_CREATED_SOURCE.SURVEY_WIZARD),
    })

    const handleAiSubmit = (): void => {
        if (prompt.trim()) {
            reportSurveyAiPromptSubmitted(SURVEY_CREATED_SOURCE.SURVEY_WIZARD)
            openMax?.()
            setPrompt('')
        }
    }

    return (
        <div className="space-y-6">
            <div className="text-center space-y-2">
                <h1 className="text-2xl font-semibold">Choose a survey template</h1>
                <p className="text-secondary">Start with a proven template, then customize it to your needs</p>
            </div>

            {/* Core templates - 2x2 grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {coreTemplates.map((template) => (
                    <TemplateCard
                        key={template.templateType}
                        template={template}
                        onClick={() => selectTemplate(template)}
                        featured
                    />
                ))}
            </div>

            {/* Other templates - collapsible */}
            {otherTemplates.length > 0 && (
                <div className="space-y-4">
                    <LemonButton
                        type="tertiary"
                        onClick={() => setShowOthers(!showOthers)}
                        icon={showOthers ? <IconChevronDown /> : <IconChevronRight />}
                    >
                        More templates ({otherTemplates.length})
                    </LemonButton>

                    {showOthers && (
                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                            {otherTemplates.map((template) => (
                                <TemplateCard
                                    key={template.templateType}
                                    template={template}
                                    onClick={() => selectTemplate(template)}
                                />
                            ))}
                        </div>
                    )}
                </div>
            )}

            <div className="flex items-center gap-4">
                <div className="flex-1 border-t border-border" />
                <span className="text-xs text-tertiary uppercase tracking-wide">
                    or tell PostHog AI what you want to learn
                </span>
                <div className="flex-1 border-t border-border" />
            </div>

            <div className="rounded-xl border-2 border-[var(--color-ai)]">
                <label
                    htmlFor="wizard-ai-prompt"
                    className="flex flex-col cursor-text"
                    onClick={() => textAreaRef.current?.focus()}
                >
                    <LemonTextArea
                        id="wizard-ai-prompt"
                        ref={textAreaRef}
                        value={prompt}
                        onChange={setPrompt}
                        onPressEnter={handleAiSubmit}
                        placeholder="e.g., Create an NPS survey for users who completed onboarding"
                        minRows={2}
                        maxRows={5}
                        className="!border-none !bg-transparent !shadow-none !rounded-none px-4 pt-4 pb-2 resize-none text-sm"
                        hideFocus
                        data-attr="wizard-ai-prompt-input"
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
                            onClick={handleAiSubmit}
                            disabledReason={!prompt.trim() ? 'Describe the survey you want' : undefined}
                            data-attr="wizard-ai-prompt-submit"
                        >
                            Create with AI
                        </LemonButton>
                    </div>
                </label>
            </div>

            <p className="text-center text-xs text-muted">
                Need more control?{' '}
                <button type="button" onClick={handleCustomizeMore} className="text-link hover:underline">
                    Open full editor
                </button>
            </p>
        </div>
    )
}
