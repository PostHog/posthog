import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import posthog from 'posthog-js'

import * as judgePng from '@posthog/brand/hoggies/png/judge'
import {
    IconArrowLeft,
    IconCode,
    IconEmoji,
    IconEye,
    IconPlus,
    IconSearch,
    IconTarget,
    IconThumbsUp,
    IconWarning,
    IconWrench,
} from '@posthog/icons'
import { LemonButton, LemonTag, LemonTagType, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { EvaluationTemplate, defaultEvaluationTemplates } from './templates'

const HedgehogJudge = pngHoggie(judgePng)

// Display order for the template list: sentiment, then Hog, then LLM judge.
const TEMPLATE_TYPE_ORDER: Record<EvaluationTemplate['evaluation_type'], number> = {
    sentiment: 0,
    hog: 1,
    llm_judge: 2,
}
const orderedTemplates = [...defaultEvaluationTemplates].sort(
    (a, b) => TEMPLATE_TYPE_ORDER[a.evaluation_type] - TEMPLATE_TYPE_ORDER[b.evaluation_type]
)

export const scene: SceneExport = {
    component: EvaluationTemplatesScene,
}

interface TemplateRowProps {
    template: EvaluationTemplate | 'blank'
}

function getTemplateIcon(icon: EvaluationTemplate['icon']): JSX.Element {
    const iconClass = 'w-6 h-6 text-primary-3000'
    switch (icon) {
        case 'target':
            return <IconTarget className={iconClass} />
        case 'thumbs-up':
            return <IconThumbsUp className={iconClass} />
        case 'eye':
            return <IconEye className={iconClass} />
        case 'alert-triangle':
            return <IconWarning className={iconClass} />
        case 'code':
            return <IconCode className={iconClass} />
        case 'search':
            return <IconSearch className={iconClass} />
        case 'wrench':
            return <IconWrench className={iconClass} />
        case 'emoji':
            return <IconEmoji className={iconClass} />
        default: {
            const exhaustiveCheck: never = icon
            return exhaustiveCheck
        }
    }
}

function getTemplateTypeTag(evaluationType: EvaluationTemplate['evaluation_type']): {
    label: string
    type: LemonTagType
} {
    switch (evaluationType) {
        case 'hog':
            return { label: 'Hog', type: 'option' }
        case 'sentiment':
            return { label: 'Sentiment', type: 'success' }
        case 'llm_judge':
            return { label: 'LLM judge', type: 'caution' }
        default: {
            const exhaustiveCheck: never = evaluationType
            return exhaustiveCheck
        }
    }
}

function TemplateRow({ template }: TemplateRowProps): JSX.Element {
    const isBlank = template === 'blank'
    const typeTag = isBlank ? null : getTemplateTypeTag(template.evaluation_type)
    const { searchParams } = useValues(router)

    const handleClick = (): void => {
        posthog.capture('llm evaluation template selected', {
            template_key: isBlank ? 'blank' : template.key,
        })

        if (isBlank) {
            router.actions.push(combineUrl(urls.aiObservabilityEvaluation('new'), searchParams).url)
        } else {
            const url = combineUrl(urls.aiObservabilityEvaluation('new'), {
                ...searchParams,
                template: template.key,
            }).url
            router.actions.push(url)
        }
    }

    return (
        <button
            className="flex items-center gap-4 w-full text-left px-4 py-3 hover:bg-fill-highlight-50 focus:bg-fill-highlight-50 focus:outline-none transition-colors cursor-pointer"
            data-attr={isBlank ? 'blank-evaluation-template' : `evaluation-template-${template.key}`}
            onClick={handleClick}
        >
            <div className="bg-primary-3000/10 rounded-lg flex-shrink-0 size-10 flex items-center justify-center">
                {isBlank ? <IconPlus className="w-5 h-5 text-primary-3000" /> : getTemplateIcon(template.icon)}
            </div>
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                    <h3 className="text-base font-semibold text-default mb-0">
                        {isBlank ? 'Create from scratch' : template.name}
                    </h3>
                    {typeTag && (
                        <LemonTag type={typeTag.type} size="small">
                            {typeTag.label}
                        </LemonTag>
                    )}
                </div>
                <p className="text-sm text-secondary mb-0">
                    {isBlank
                        ? 'Build a custom evaluation with your own configuration'
                        : template.description}
                </p>
            </div>
        </button>
    )
}

interface TemplateGridProps {
    title: string
    description: string
    showBackButton?: boolean
    learnMoreUrl?: string
    minHeight?: '60vh' | '80vh'
}

function TemplateGrid({
    title,
    description,
    showBackButton = false,
    learnMoreUrl,
    minHeight = '60vh',
}: TemplateGridProps): JSX.Element {
    const { searchParams } = useValues(router)

    return (
        <div className="flex flex-col items-center justify-center py-8" style={{ minHeight }}>
            <div className="w-full max-w-5xl px-4">
                {showBackButton && (
                    <div className="mb-6">
                        <LemonButton
                            type="secondary"
                            icon={<IconArrowLeft />}
                            onClick={() =>
                                router.actions.push(combineUrl(urls.aiObservabilityEvaluations(), searchParams).url)
                            }
                            size="small"
                        >
                            Back to Evaluations
                        </LemonButton>
                    </div>
                )}
                <div className="space-y-8">
                    <div className="text-center space-y-3">
                        <div className="flex justify-center mb-4">
                            <HedgehogJudge className="w-32 h-32" />
                        </div>
                        <h1 className="text-3xl font-bold">{title}</h1>
                        <p className="text-base text-secondary max-w-2xl mx-auto">
                            {description}
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

                    <div className="flex flex-col border border-border rounded-lg divide-y divide-border overflow-hidden bg-bg-light">
                        <TemplateRow template="blank" />
                        {orderedTemplates.map((template) => (
                            <TemplateRow key={template.key} template={template} />
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}

export function EvaluationTemplatesScene(): JSX.Element {
    return (
        <TemplateGrid
            title="Choose an evaluation template"
            description="Select a pre-configured template to get started quickly, or create your own from scratch"
            showBackButton
            minHeight="80vh"
        />
    )
}

export function EvaluationTemplatesEmptyState(): JSX.Element {
    return (
        <TemplateGrid
            title="Create your first evaluation"
            description="Select a pre-configured template to get started quickly, or create your own from scratch."
            showBackButton={false}
            learnMoreUrl="https://posthog.com/docs/ai-evals/evaluations"
            minHeight="60vh"
        />
    )
}
