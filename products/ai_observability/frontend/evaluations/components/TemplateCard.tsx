import posthog from 'posthog-js'

import { IconEye } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonTag } from '@posthog/lemon-ui'

import type { EvaluationTemplate } from '../templates'
import { TemplateIcon } from './TemplateIcon'
import { TemplateOutputPreview } from './TemplateOutputPreview'
import { TemplatePreview } from './TemplatePreview'
import { METHOD_TAGS } from './templateSummary'

export function TemplateCard({
    template,
    onSelect,
}: {
    template: EvaluationTemplate
    onSelect: (template: EvaluationTemplate, placement: 'card' | 'example') => void
}): JSX.Element {
    return (
        <div className="group relative flex h-full rounded-lg border border-primary bg-surface-primary hover:border-accent transition-colors motion-reduce:transition-none">
            <button
                type="button"
                className="flex flex-1 min-w-0 gap-3 p-3 text-left cursor-pointer rounded-lg"
                data-attr={`evaluation-template-${template.key}`}
                onClick={() => onSelect(template, 'card')}
            >
                <TemplateIcon template={template} />
                <div className="flex flex-col flex-1 min-w-0 gap-0.5">
                    <div className="flex items-center gap-2">
                        <h3 className="m-0 text-sm font-semibold truncate">{template.name}</h3>
                        <LemonTag type={METHOD_TAGS[template.evaluation_type].type} size="small">
                            {METHOD_TAGS[template.evaluation_type].label}
                        </LemonTag>
                    </div>
                    <p className="m-0 text-xs text-secondary line-clamp-2">{template.description}</p>
                    <div className="mt-auto pt-2">
                        <TemplateOutputPreview template={template} />
                    </div>
                </div>
            </button>
            <div className="absolute top-2 right-2 rounded bg-surface-primary opacity-0 group-hover:opacity-100 has-[:focus-visible]:opacity-100 has-[[aria-expanded=true]]:opacity-100 transition-opacity motion-reduce:transition-none">
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
                            posthog.capture('llm evaluation template example opened', { template_key: template.key })
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
    )
}
