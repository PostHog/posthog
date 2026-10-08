import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { autoresearchNewLogic } from '../autoresearchNewLogic'

export function TemplateChips(): JSX.Element | null {
    const { templates, templatesLoading, newPipeline, resolvedTemplateLoading } = useValues(autoresearchNewLogic)
    const { selectTemplate } = useActions(autoresearchNewLogic)

    if (templatesLoading && templates.length === 0) {
        return <LemonSkeleton className="h-8 w-full" />
    }
    // Without templates the form is the custom definition, so a lone Custom chip adds nothing.
    if (templates.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <h3 className="text-base font-semibold mb-0">Start from a template</h3>
            <div className="flex flex-wrap gap-2">
                {templates.map((template) => (
                    <LemonButton
                        key={template.key}
                        type="secondary"
                        size="small"
                        active={newPipeline.template_key === template.key}
                        loading={resolvedTemplateLoading && newPipeline.template_key === template.key}
                        tooltip={template.description}
                        onClick={() => selectTemplate(template.key)}
                        data-attr={`autoresearch-new-template-${template.key}`}
                    >
                        {template.display_name}
                    </LemonButton>
                ))}
                <LemonButton
                    type="secondary"
                    size="small"
                    active={newPipeline.template_key === null}
                    tooltip="Define the target, population, and horizon yourself. Supports actions as targets."
                    onClick={() => selectTemplate(null)}
                    data-attr="autoresearch-new-template-custom"
                >
                    Custom
                </LemonButton>
            </div>
        </div>
    )
}
