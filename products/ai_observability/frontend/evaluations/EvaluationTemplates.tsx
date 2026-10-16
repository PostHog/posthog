import { useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useState } from 'react'

import * as judgePng from '@posthog/brand/hoggies/png/judge'
import { IconArrowLeft, IconChevronRight, IconPlus } from '@posthog/icons'
import { LemonButton, LemonTabs, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { SceneExport } from 'scenes/sceneTypes'

import { EvaluationAgentCard } from './components/EvaluationAgentCard'
import { TemplateCard } from './components/TemplateCard'
import { getEvaluationBackTarget, getEvaluationTemplateSelectionUrl } from './evaluationNavigation'
import { EvaluationTemplate, EvaluationTemplateCategory, defaultEvaluationTemplates } from './templates'

const HedgehogJudge = pngHoggie(judgePng)

// Ordered by how many people picked each template in the last 180 days.
const POPULAR_TEMPLATE_KEYS = ['relevance', 'cost_latency', 'helpfulness', 'hallucination', 'sentiment', 'toxicity']
// One score and one category template first so people see those output types, then the most picked ones.
// Sentiment is here for its recent picks, even though it ranks lower over 180 days.
const RECOMMENDED_TEMPLATE_KEYS = [
    'response_quality',
    'task_outcome',
    'sentiment',
    'relevance',
    'helpfulness',
    'cost_latency',
]

type TemplateTab = 'recommended' | 'all' | EvaluationTemplateCategory

const CATEGORY_TABS: { key: EvaluationTemplateCategory; label: string }[] = [
    { key: 'quality', label: 'Answer quality' },
    { key: 'safety', label: 'Safety' },
    { key: 'agents', label: 'Agent behavior' },
    { key: 'users', label: 'User insights' },
    { key: 'cost_speed', label: 'Cost & speed' },
]

const byKeys = (keys: string[]): EvaluationTemplate[] =>
    keys.flatMap((key) => defaultEvaluationTemplates.filter((template) => template.key === key))

const ALL_TEMPLATES_POPULAR_FIRST = [
    ...byKeys(POPULAR_TEMPLATE_KEYS),
    ...defaultEvaluationTemplates.filter((template) => !POPULAR_TEMPLATE_KEYS.includes(template.key)),
]

function templatesForTab(tab: TemplateTab): EvaluationTemplate[] {
    if (tab === 'recommended') {
        return byKeys(RECOMMENDED_TEMPLATE_KEYS)
    }
    if (tab === 'all') {
        return ALL_TEMPLATES_POPULAR_FIRST
    }
    return ALL_TEMPLATES_POPULAR_FIRST.filter((template) => template.category === tab)
}

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
    const [tab, setTab] = useState<TemplateTab>('recommended')
    const templates = templatesForTab(tab)

    const selectTab = (key: TemplateTab): void => {
        setTab(key)
        posthog.capture('llm evaluation template tab selected', { tab: key })
    }

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
                <div className="flex items-center min-w-0 gap-4">
                    <HedgehogJudge className="hidden @min-[40rem]/templates:block size-24 shrink-0" />
                    <div className="flex flex-col min-w-0 gap-2">
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
                    </div>
                </div>
                <div className="flex flex-col gap-2">
                    <button
                        type="button"
                        className="group flex items-center gap-3 p-3 text-left rounded-lg border border-primary bg-surface-primary cursor-pointer hover:border-accent transition-colors motion-reduce:transition-none"
                        data-attr="blank-evaluation-template"
                        onClick={() => selectTemplate(null, 'card')}
                    >
                        <div className="flex items-center justify-center size-10 shrink-0 rounded-lg bg-fill-secondary text-accent">
                            <IconPlus className="size-5" />
                        </div>
                        <div className="flex-1 min-w-0">
                            <h2 className="m-0 text-sm font-semibold">Start from scratch</h2>
                            <p className="m-0 text-xs text-secondary">Write your own prompt or Hog code.</p>
                        </div>
                        <IconChevronRight className="size-5 shrink-0 text-secondary transition-transform group-hover:translate-x-0.5 motion-reduce:transition-none" />
                    </button>
                    <EvaluationAgentCard />
                </div>
            </div>

            <div className="flex flex-col gap-2">
                <LemonTabs
                    activeKey={tab}
                    onChange={selectTab}
                    tabs={[
                        { key: 'recommended', label: 'Recommended' },
                        { key: 'all', label: 'All' },
                        ...CATEGORY_TABS,
                    ]}
                    data-attr="evaluation-template-tabs"
                />
                <div className="grid grid-cols-1 gap-2 @min-[36rem]/templates:grid-cols-2 @min-[60rem]/templates:grid-cols-3">
                    {templates.map((template) => (
                        <TemplateCard key={template.key} template={template} onSelect={selectTemplate} />
                    ))}
                </div>
                {tab === 'recommended' && (
                    <div>
                        <LemonButton type="tertiary" size="small" onClick={() => selectTab('all')}>
                            {`See all ${defaultEvaluationTemplates.length} templates`}
                        </LemonButton>
                    </div>
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
