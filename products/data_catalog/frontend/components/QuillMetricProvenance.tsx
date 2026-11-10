import { Collapsible, CollapsibleContent, CollapsibleTrigger, Text } from '@posthog/quill'

import type { DataCatalogMetricApi } from '../generated/api.schemas'

export function QuillMetricProvenance({ metric }: { metric: DataCatalogMetricApi }): JSX.Element | null {
    if (metric.created_source !== 'ai_generated') {
        return null
    }
    return (
        <Collapsible>
            <CollapsibleTrigger>AI provenance</CollapsibleTrigger>
            <CollapsibleContent className="flex flex-col gap-1">
                {metric.ai_model && <Text size="xs">Model: {metric.ai_model}</Text>}
                {metric.confidence != null && <Text size="xs">Confidence: {Math.round(metric.confidence * 100)}%</Text>}
                {metric.reasoning && <Text size="xs">{metric.reasoning}</Text>}
            </CollapsibleContent>
        </Collapsible>
    )
}
