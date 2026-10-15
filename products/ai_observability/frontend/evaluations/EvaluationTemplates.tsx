import { useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import * as judgePng from '@posthog/brand/hoggies/png/judge'
import { IconArrowLeft, IconPlus } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { SceneExport } from 'scenes/sceneTypes'

import { EvaluationAgentCard } from './components/EvaluationAgentCard'
import { TemplateCard } from './components/TemplateCard'
import { getEvaluationBackTarget, getEvaluationTemplateSelectionUrl } from './evaluationNavigation'
import { EvaluationTemplate, defaultEvaluationTemplates } from './templates'

const HedgehogJudge = pngHoggie(judgePng)

// Ordered by how many people picked each template in the last 180 days.
const POPULAR_TEMPLATE_KEYS = ['relevance', 'cost_latency', 'helpfulness', 'hallucination', 'sentiment', 'toxicity']

export const scene: SceneExport = {
    component: EvaluationTemplatesScene,
}

interface TemplatePickerProps {
    title: string
    showBackButton?: boolean
    learnMoreUrl?: string
}

function TemplatePicker({ title, showBackButton = false, learnMoreUrl }: TemplatePickerProps): JSX.Element {
    const { searchParams } = useValues(router)
    const popular = POPULAR_TEMPLATE_KEYS.flatMap((key) =>
        defaultEvaluationTemplates.filter((template) => template.key === key)
    )
    const others = defaultEvaluationTemplates.filter((template) => !POPULAR_TEMPLATE_KEYS.includes(template.key))

    const selectTemplate = (template: EvaluationTemplate | null, placement: 'card' | 'example'): void => {
        // pinned: analytics event name and template_key values - renaming them breaks existing dashboards
        posthog.capture('llm evaluation template selected', {
            template_key: template?.key ?? 'blank',
            output_type: template?.output_type,
            placement,
        })
        router.actions.push(getEvaluationTemplateSelectionUrl(searchParams, template?.key))
    }

    return (
        <div className="@container/templates flex flex-col gap-6 w-full max-w-6xl mx-auto px-4 py-6">
            {showBackButton && (
                <div>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconArrowLeft />}
                        onClick={() => router.actions.push(getEvaluationBackTarget(false, searchParams).path)}
                    >
                        Back to evaluations
                    </LemonButton>
                </div>
            )}
            <div className="grid grid-cols-1 gap-4 items-center @min-[56rem]/templates:grid-cols-[2fr_3fr]">
                <div className="flex flex-col min-w-0 gap-2">
                    <HedgehogJudge className="hidden @min-[40rem]/templates:block size-20 shrink-0" />
                    <h1 className="m-0 text-3xl font-bold">{title}</h1>
                    <p className="m-0 text-base text-secondary">
                        <span>Start with a template, or let your agent suggest evaluations from your traces.</span>
                        {learnMoreUrl && (
                            <>
                                {' '}
                                <Link to={learnMoreUrl} target="_blank">
                                    Learn more
                                </Link>
                            </>
                        )}
                    </p>
                    <div className="pt-1">
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            data-attr="blank-evaluation-template"
                            onClick={() => selectTemplate(null, 'card')}
                        >
                            Create from scratch
                        </LemonButton>
                    </div>
                </div>
                <EvaluationAgentCard />
            </div>

            <div className="flex flex-col gap-4">
                {[
                    { title: 'Popular', items: popular },
                    { title: 'More templates', items: others },
                ].map(
                    (section) =>
                        section.items.length > 0 && (
                            <section key={section.title} className="flex flex-col gap-2">
                                <h2 className="m-0 text-sm font-semibold text-secondary">{section.title}</h2>
                                <div className="grid grid-cols-1 gap-2 @min-[36rem]/templates:grid-cols-2 @min-[60rem]/templates:grid-cols-3">
                                    {section.items.map((template) => (
                                        <TemplateCard
                                            key={template.key}
                                            template={template}
                                            onSelect={selectTemplate}
                                        />
                                    ))}
                                </div>
                            </section>
                        )
                )}
            </div>
        </div>
    )
}

export function EvaluationTemplatesScene(): JSX.Element {
    return <TemplatePicker title="Create an evaluation" showBackButton />
}

export function EvaluationTemplatesEmptyState(): JSX.Element {
    return (
        <TemplatePicker
            title="Create your first evaluation"
            learnMoreUrl="https://posthog.com/docs/ai-evals/evaluations"
        />
    )
}
