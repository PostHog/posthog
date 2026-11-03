import type { ReactNode } from 'react'

import { Collapsible, CollapsibleContent, CollapsibleTrigger, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import type { DataCatalogMetricApi } from '../generated/api.schemas'
import { MetricOwnerCombobox } from '../metrics/MetricOwnerCombobox'
import { QuillMetricStatusBadges } from './QuillMetricStatusBadges'
import { QuillMetricUnitEditor } from './QuillMetricUnitEditor'

export interface QuillMetricMetadataProps {
    metric: DataCatalogMetricApi
    saving: boolean
    onSaveUnit: (unit: string) => void
    onSaveOwner: (owner: string | null) => void
}

function MetadataItem({ label, value }: { label: string; value: ReactNode }): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-1">
            <Text size="xs" variant="muted" render={<span />}>
                {label}
            </Text>
            <Text size="xs" render={<span />} className="min-w-0 truncate">
                {value}
            </Text>
        </div>
    )
}

export function QuillMetricMetadata({
    metric,
    saving,
    onSaveUnit,
    onSaveOwner,
}: QuillMetricMetadataProps): JSX.Element {
    const showProvenance = metric.created_source === 'ai_generated'

    return (
        <div className="flex flex-col gap-4">
            <QuillMetricStatusBadges metric={metric} />
            <div className="grid max-w-2xl grid-cols-2 gap-x-8 gap-y-2">
                <MetadataItem
                    label="Owner"
                    value={
                        <MetricOwnerCombobox
                            label={metric.owner || 'Unassigned'}
                            variant="default"
                            loading={saving}
                            onChange={onSaveOwner}
                            dataAttr="data-catalog-metric-owner-select"
                        />
                    }
                />
                <MetadataItem label="Approved by" value={metric.approved_by?.email || 'Not approved'} />
                <MetadataItem
                    label="Approved at"
                    value={metric.approved_at ? <TZLabel time={metric.approved_at} /> : 'Not approved'}
                />
                <MetadataItem
                    label="Last run"
                    value={metric.last_run_at ? <TZLabel time={metric.last_run_at} /> : 'Never'}
                />
            </div>
            {showProvenance && (
                <Collapsible>
                    <CollapsibleTrigger>AI provenance</CollapsibleTrigger>
                    <CollapsibleContent className="flex flex-col gap-1">
                        {metric.ai_model && <Text size="xs">Model: {metric.ai_model}</Text>}
                        {metric.confidence != null && (
                            <Text size="xs">Confidence: {Math.round(metric.confidence * 100)}%</Text>
                        )}
                        {metric.reasoning && <Text size="xs">{metric.reasoning}</Text>}
                    </CollapsibleContent>
                </Collapsible>
            )}
            <QuillMetricUnitEditor key={metric.unit || ''} unit={metric.unit || ''} onSave={onSaveUnit} />
        </div>
    )
}
