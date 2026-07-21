import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconDatabase, IconServer } from '@posthog/icons'
import { LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import { IconTableChart } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { escapeDottedHogQLIdentifier } from '~/queries/utils'

import { DataSource, outputPaneLogic } from '../outputPaneLogic'
import { sqlEditorLogic } from '../sqlEditorLogic'
import { DataSourcePickerModal, PickerKind } from './DataSourcePickerModal'
import { insightBuilderLogic } from './insightBuilderLogic'

/**
 * The top "Data source" row of the builder: choose View / Warehouse source / Custom SQL. View and
 * Warehouse open a picker and then show a compact badge; Custom SQL reveals the SQL editor passed
 * as `children` (tree + query pane).
 */
export function DataSourceRow({ tabId, children }: { tabId: string; children: React.ReactNode }): JSX.Element {
    const { dataSource } = useValues(outputPaneLogic({ tabId }))
    const { setDataSource } = useActions(outputPaneLogic({ tabId }))
    const { baseViewName } = useValues(insightBuilderLogic({ tabId }))
    const { setQueryInput, runQuery } = useActions(sqlEditorLogic({ tabId }))

    const [pickerKind, setPickerKind] = useState<PickerKind | null>(null)

    const onPick = (kind: PickerKind, name: string): void => {
        const query = `SELECT * FROM ${escapeDottedHogQLIdentifier(name)} LIMIT 100`
        setQueryInput(query)
        runQuery(query)
        // detectSelectAllTarget in refreshBase (fired by setDataSource) picks the object name up as baseView
        setDataSource(kind === 'view' ? DataSource.View : DataSource.Warehouse)
    }

    const onSelectSegment = (value: DataSource): void => {
        if (value === DataSource.Sql) {
            setDataSource(DataSource.Sql)
            return
        }
        const kind: PickerKind = value === DataSource.View ? 'view' : 'warehouse'
        // Open the picker; dataSource commits on pick
        setPickerKind(kind)
    }

    return (
        <div className="flex flex-col border-b bg-surface-primary">
            <div className="flex items-center gap-3 px-3 py-2">
                <span className="text-xs font-semibold uppercase text-tertiary">Data source</span>
                <LemonSegmentedButton
                    size="small"
                    value={dataSource ?? undefined}
                    onChange={(value) => onSelectSegment(value as DataSource)}
                    options={[
                        { value: DataSource.View, label: 'View', icon: <IconTableChart /> },
                        { value: DataSource.Warehouse, label: 'Warehouse source', icon: <IconServer /> },
                        { value: DataSource.Sql, label: 'Custom SQL', icon: <IconDatabase /> },
                    ]}
                />
                {(dataSource === DataSource.View || dataSource === DataSource.Warehouse) && baseViewName ? (
                    <div className="flex items-center gap-2">
                        <LemonTag type="highlight" icon={<IconDatabase />} className="max-w-60 truncate">
                            {baseViewName}
                        </LemonTag>
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => setPickerKind(dataSource === DataSource.View ? 'view' : 'warehouse')}
                        >
                            Change
                        </LemonButton>
                    </div>
                ) : null}
            </div>

            {dataSource === null ? (
                <div className="px-3 pb-3 text-sm text-secondary">Choose a data source to start building.</div>
            ) : null}

            {dataSource === DataSource.Sql ? (
                <div className="flex min-h-0 flex-1 overflow-hidden">{children}</div>
            ) : null}

            <DataSourcePickerModal
                kind={pickerKind ?? 'view'}
                isOpen={pickerKind !== null}
                onClose={() => setPickerKind(null)}
                onPick={(name) => onPick(pickerKind ?? 'view', name)}
            />
        </div>
    )
}
