import posthog from 'posthog-js'

import { IconEye } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { EvaluationTemplate } from '../templates'
import { TemplateIcon } from './TemplateIcon'
import { TemplatePreview } from './TemplatePreview'
import { METHOD_TAGS, templateOutputText } from './templateSummary'

// Score and category outputs are recently released, so their templates carry a badge to get noticed.
function isNewOutputType(template: EvaluationTemplate): boolean {
    return template.output_type === 'numeric' || template.output_type === 'categorical'
}

export function TemplateCard({
    template,
    onSelect,
}: {
    template: EvaluationTemplate
    onSelect: (template: EvaluationTemplate, placement: 'card' | 'example') => void
}): JSX.Element {
    return (
        <div className="relative flex h-full gap-3 p-3 overflow-hidden rounded-lg border border-primary bg-surface-primary hover:border-accent transition-colors motion-reduce:transition-none">
            {isNewOutputType(template) && (
                // Font size and line height match a small LemonTag, which has no filled variant for a corner label.
                // The card clips it, so its corner follows the card's inner border radius.
                <span className="absolute top-0 right-0 px-1.5 py-0.5 rounded-bl-lg bg-accent text-white text-[0.625rem] leading-[0.875rem] font-medium pointer-events-none">
                    New
                </span>
            )}
            <TemplateIcon template={template} />
            <div className="flex flex-col flex-1 min-w-0 gap-0.5">
                <div className={cn('flex items-center gap-2', isNewOutputType(template) && 'pr-10')}>
                    <h3 className="m-0 text-sm font-semibold truncate">
                        {/* The pseudo-element stretches this button over the whole card, so the card is one click target and the Example button can still sit inside it. */}
                        <button
                            type="button"
                            className="text-left cursor-pointer after:absolute after:inset-0 after:rounded-lg focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-accent"
                            data-attr={`evaluation-template-${template.key}`}
                            onClick={() => onSelect(template, 'card')}
                        >
                            {template.name}
                        </button>
                    </h3>
                    <LemonTag type="muted" size="small">
                        {METHOD_TAGS[template.evaluation_type]}
                    </LemonTag>
                </div>
                {/* As a flex item with hidden overflow, the description would shrink in a short card and cut its clamped lines in half. */}
                <p className="m-0 shrink-0 text-xs text-secondary line-clamp-2">{template.description}</p>
                <div className="flex items-center justify-between gap-2 mt-auto pt-1">
                    <span className="text-xs text-muted truncate">{templateOutputText(template)}</span>
                    <div className="relative z-10 shrink-0">
                        <LemonDropdown
                            overlay={
                                <div className="w-[24rem] max-w-[calc(100vw-2rem)]">
                                    <TemplatePreview
                                        template={template}
                                        onSelect={(selected) => onSelect(selected, 'example')}
                                    />
                                </div>
                            }
                            placement="right-start"
                            fallbackPlacements={['left-start', 'bottom-end']}
                            closeOnClickInside={false}
                            onVisibilityChange={(visible) => {
                                if (visible) {
                                    posthog.capture('llm evaluation template example opened', {
                                        template_key: template.key,
                                    })
                                }
                            }}
                        >
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                icon={<IconEye />}
                                data-attr={`evaluation-template-example-${template.key}`}
                            >
                                Example
                            </LemonButton>
                        </LemonDropdown>
                    </div>
                </div>
            </div>
        </div>
    )
}
