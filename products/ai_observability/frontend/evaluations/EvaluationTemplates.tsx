import { useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import * as judgePng from '@posthog/brand/hoggies/png/judge'
import {
    IconArrowLeft,
    IconCode,
    IconEmoji,
    IconEye,
    IconPlus,
    IconSearch,
    IconSparkles,
    IconTarget,
    IconThumbsUp,
    IconWarning,
    IconWrench,
} from '@posthog/icons'
import { LemonButton, LemonTag, LemonTagType, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { useOpenAi } from '~/scenes/max/useOpenAi'

import { getEvaluationBackTarget, getEvaluationTemplateSelectionUrl } from './evaluationNavigation'
import { EvaluationTemplate, defaultEvaluationTemplates } from './templates'

const HedgehogJudge = pngHoggie(judgePng)

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

interface PickerRowProps {
    dataAttr: string
    description: string
    icon: JSX.Element
    onClick: () => void
    tag?: {
        label: string
        type: LemonTagType
    }
    title: string
}

function PickerRow({ dataAttr, description, icon, onClick, tag, title }: PickerRowProps): JSX.Element {
    return (
        <button
            className="flex items-center gap-4 w-full text-left px-4 py-3 hover:bg-fill-highlight-50 focus:bg-fill-highlight-50 focus:outline-none transition-colors cursor-pointer"
            data-attr={dataAttr}
            onClick={onClick}
        >
            <div className="bg-primary-3000/10 rounded-lg flex-shrink-0 size-10 flex items-center justify-center">
                {icon}
            </div>
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                    <h3 className="text-base font-semibold text-default mb-0">{title}</h3>
                    {tag && (
                        <LemonTag type={tag.type} size="small">
                            {tag.label}
                        </LemonTag>
                    )}
                </div>
                <p className="text-sm text-secondary mb-0">{description}</p>
            </div>
        </button>
    )
}

function TemplateRow({ template }: TemplateRowProps): JSX.Element {
    const isBlank = template === 'blank'
    const typeTag = isBlank ? null : getTemplateTypeTag(template.evaluation_type)
    const { searchParams } = useValues(router)

    const handleClick = (): void => {
        posthog.capture('llm evaluation template selected', {
            template_key: isBlank ? 'blank' : template.key,
        })

        router.actions.push(getEvaluationTemplateSelectionUrl(searchParams, isBlank ? undefined : template.key))
    }

    return (
        <PickerRow
            dataAttr={isBlank ? 'blank-evaluation-template' : `evaluation-template-${template.key}`}
            description={isBlank ? 'Build a custom evaluation with your own configuration' : template.description}
            icon={isBlank ? <IconPlus className="w-5 h-5 text-primary-3000" /> : getTemplateIcon(template.icon)}
            onClick={handleClick}
            tag={typeTag ?? undefined}
            title={isBlank ? 'Create from scratch' : template.name}
        />
    )
}

function StartWithAiRow(): JSX.Element {
    const { openAi } = useOpenAi()

    const handleClick = (): void => {
        posthog.capture('llm evaluation template selected', { template_key: 'start_with_ai' })
        openAi(
            'Create an online evaluation for me. First explore my recent AI traces to find failure modes worth evaluating, then set one up to catch the most important one.'
        )
    }

    return (
        <PickerRow
            dataAttr="start-with-ai-evaluation-template"
            description="Let PostHog AI explore your traces and build an evaluation for you"
            icon={<IconSparkles className="w-5 h-5 text-primary-3000" />}
            onClick={handleClick}
            tag={{ label: 'Beta', type: 'completion' }}
            title="Start with AI"
        />
    )
}

interface TemplatePickerProps {
    title: string
    description: string
    showBackButton?: boolean
    learnMoreUrl?: string
    minHeight?: '60vh' | '80vh'
}

function TemplatePicker({
    title,
    description,
    showBackButton = false,
    learnMoreUrl,
    minHeight = '60vh',
}: TemplatePickerProps): JSX.Element {
    const { searchParams } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const showStartWithAi = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_START_WITH_AI]

    return (
        <div className="flex flex-col items-center justify-center py-8" style={{ minHeight }}>
            <div className="w-full max-w-5xl px-4">
                {showBackButton && (
                    <div className="mb-6">
                        <LemonButton
                            type="secondary"
                            icon={<IconArrowLeft />}
                            onClick={() => router.actions.push(getEvaluationBackTarget(false, searchParams).path)}
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
                        {showStartWithAi && <StartWithAiRow />}
                        <TemplateRow template="blank" />
                        {defaultEvaluationTemplates.map((template) => (
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
        <TemplatePicker
            title="Choose an evaluation template"
            description="Select a pre-configured template to get started quickly, or create your own from scratch"
            showBackButton
            minHeight="80vh"
        />
    )
}

export function EvaluationTemplatesEmptyState(): JSX.Element {
    return (
        <TemplatePicker
            title="Create your first evaluation"
            description="Select a pre-configured template to get started quickly, or create your own from scratch."
            showBackButton={false}
            learnMoreUrl="https://posthog.com/docs/ai-evals/evaluations"
            minHeight="60vh"
        />
    )
}
