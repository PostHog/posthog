import { useValues } from 'kea'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { metricsLogic } from '../metricsLogic'
import type { CatalogReferenceKind } from './metricMarkdownSlashCommands'

export function CatalogReferencePickerModal({
    kind,
    onSelect,
    onClose,
}: {
    kind: CatalogReferenceKind
    onSelect: (name: string) => void
    onClose: () => void
}): JSX.Element {
    const { allMetrics, allMetricsLoading } = useValues(metricsLogic)
    const { allTables, databaseLoading } = useValues(databaseTableListLogic)

    const isMetric = kind === 'metric'
    const options = isMetric
        ? allMetrics.map((metric) => ({ key: metric.name, label: metric.name }))
        : allTables.map((table) => ({ key: table.name, label: table.name }))

    return (
        <LemonModal isOpen onClose={onClose} width={480} title={isMetric ? 'Reference a metric' : 'Reference a table'}>
            <LemonModal.Content>
                <LemonInputSelect
                    mode="single"
                    value={[]}
                    onChange={(values) => values[0] && onSelect(values[0])}
                    options={options}
                    loading={isMetric ? allMetricsLoading : databaseLoading}
                    placeholder={isMetric ? 'Search metrics' : 'Search tables'}
                    autoFocus
                    data-attr="data-catalog-reference-picker"
                />
            </LemonModal.Content>
        </LemonModal>
    )
}
