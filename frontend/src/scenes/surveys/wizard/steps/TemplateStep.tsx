import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import {
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
import { LemonButton } from '@posthog/lemon-ui'

import { SurveyTemplate, SurveyTemplateType } from '../../constants'
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

export function TemplateStep(): JSX.Element {
    const { coreTemplates, otherTemplates } = useValues(surveyWizardLogic)
    const { selectTemplate } = useActions(surveyWizardLogic)
    const [showOthers, setShowOthers] = useState(false)

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
                <div className="border-t border-border pt-6 space-y-4">
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
        </div>
    )
}
