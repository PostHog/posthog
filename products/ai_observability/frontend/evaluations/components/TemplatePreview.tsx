import { useState } from 'react'

import { IconArrowRight, IconCheck, IconChevronRight, IconX } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { EvaluationResultTag } from '../../components/EvaluationResultTag'
import { TranscriptBubbleStream } from '../../ConversationDisplay/TranscriptBubbleStream'
import { EVALUATION_TEMPLATE_EXAMPLES, EvaluationTemplateExample } from '../templateExamples'
import type { EvaluationTemplate } from '../templates'
import { TemplateIcon } from './TemplateIcon'
import { templateSummary } from './templateSummary'

function passingRuleText(template: EvaluationTemplate): string | null {
    const { passing_rule, options, true_is_failure } = template.output_config
    if (template.output_type === 'boolean') {
        return true_is_failure ? 'A run fails when the problem is found' : null
    }
    if (!passing_rule) {
        return null
    }
    if ('threshold' in passing_rule) {
        return `A run passes at ${passing_rule.threshold} or ${passing_rule.operator === 'gte' ? 'more' : 'less'}`
    }
    if (passing_rule.categories.length === 0) {
        return 'A run passes when no category applies'
    }
    const labels = passing_rule.categories.map((key) => options?.find((option) => option.key === key)?.label ?? key)
    return `A run passes when it is ${labels.join(' or ')}`
}

function ExampleResultTag({
    template,
    example,
}: {
    template: EvaluationTemplate
    example: EvaluationTemplateExample
}): JSX.Element {
    const config = template.output_config
    // A raw true or false reads as good or bad on its own, so booleans say pass or fail instead.
    if (template.output_type === 'boolean') {
        const passed = config.true_is_failure ? example.result.result === false : example.result.result === true
        return (
            <LemonTag type={passed ? 'success' : 'danger'} icon={passed ? <IconCheck /> : <IconX />}>
                {passed ? 'Pass' : 'Fail'}
            </LemonTag>
        )
    }
    return (
        <EvaluationResultTag
            run={{
                ...example.result,
                status: 'completed',
                result_type: template.output_type,
                evaluation_type: template.evaluation_type,
                score_min: config.min ?? null,
                score_max: config.max ?? null,
                applicable: true,
                skipped: false,
            }}
            passingRule={config.passing_rule}
            categoryOptions={config.options}
        />
    )
}

function ExampleDistribution({
    template,
    example,
}: {
    template: EvaluationTemplate
    example: EvaluationTemplateExample
}): JSX.Element {
    const hasPassFail = example.distribution.some((bucket) => bucket.passes !== null)
    const passRate = example.distribution.reduce((sum, bucket) => sum + (bucket.passes ? bucket.percent : 0), 0)
    const rule = passingRuleText(template)

    return (
        <div className="flex flex-col gap-2 p-3 rounded-lg border border-primary">
            <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs font-semibold">Across 1,000 runs</span>
                {hasPassFail && <span className="text-sm font-semibold text-success">{`${passRate}% pass`}</span>}
            </div>
            <div className="flex flex-col gap-1">
                {example.distribution.map((bucket) => (
                    <div key={bucket.label} className="grid grid-cols-[8rem_1fr_2.5rem] items-center gap-2 text-xs">
                        <span className="truncate">{bucket.label}</span>
                        <LemonProgress
                            percent={bucket.percent}
                            strokeColor={
                                bucket.passes === null
                                    ? 'var(--brand-blue)'
                                    : bucket.passes
                                      ? 'var(--success)'
                                      : 'var(--danger)'
                            }
                        />
                        <span className="text-right text-secondary">{`${bucket.percent}%`}</span>
                    </div>
                ))}
            </div>
            {rule && <span className="text-xs text-secondary">{rule}</span>}
        </div>
    )
}

function TemplateDefinition({ template }: { template: EvaluationTemplate }): JSX.Element | null {
    const [expanded, setExpanded] = useState(false)
    if (template.evaluation_type === 'sentiment') {
        return null
    }
    const isHog = template.evaluation_type === 'hog'
    return (
        <div className="flex flex-col gap-1">
            <div>
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconChevronRight className={expanded ? 'rotate-90' : undefined} />}
                    onClick={() => setExpanded(!expanded)}
                    data-attr="evaluation-template-example-definition"
                >
                    {isHog ? 'Show Hog code' : 'Show prompt'}
                </LemonButton>
            </div>
            {expanded && (
                <pre className="m-0 p-2 max-h-60 overflow-y-auto rounded bg-surface-secondary text-xs font-mono whitespace-pre-wrap break-words">
                    {isHog ? template.source : template.prompt}
                </pre>
            )}
        </div>
    )
}

export function TemplatePreview({
    template,
    onSelect,
}: {
    template: EvaluationTemplate
    onSelect: (template: EvaluationTemplate) => void
}): JSX.Element {
    const example = EVALUATION_TEMPLATE_EXAMPLES[template.key]

    return (
        <div className="flex flex-col gap-3 p-2">
            <div className="flex items-center gap-3">
                <TemplateIcon template={template} />
                <div className="min-w-0">
                    <h3 className="m-0 text-base font-semibold">{template.name}</h3>
                    <div className="text-xs text-secondary">{templateSummary(template)}</div>
                </div>
            </div>

            {example && (
                <>
                    {(example.messages.length > 0 || example.metrics) && (
                        <div className="flex flex-col gap-2 p-3 rounded-lg bg-surface-secondary">
                            {example.messages.length > 0 && (
                                // The stream renders inputs then outputs, so passing every message as input keeps the conversation order.
                                <TranscriptBubbleStream inputs={example.messages} outputs={[]} />
                            )}
                            {example.metrics && (
                                <div className="flex flex-wrap gap-1">
                                    {example.metrics.map((metric) => (
                                        <LemonTag key={metric.label} type="muted">
                                            {`${metric.label}: ${metric.value}`}
                                        </LemonTag>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                    <div className="flex flex-col gap-1 p-3 rounded-lg border border-primary">
                        <div className="flex flex-wrap items-center gap-2">
                            <span className="text-xs font-semibold">This run</span>
                            <ExampleResultTag template={template} example={example} />
                        </div>
                        <p className="m-0 text-xs text-secondary">{example.reasoning}</p>
                    </div>
                    <ExampleDistribution template={template} example={example} />
                </>
            )}

            <TemplateDefinition template={template} />

            <LemonButton
                type="primary"
                fullWidth
                center
                sideIcon={<IconArrowRight />}
                onClick={() => onSelect(template)}
                data-attr="evaluation-template-preview-use"
            >
                Use this template
            </LemonButton>
        </div>
    )
}
