import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { BIConnections } from 'products/business_intelligence/frontend/BIConnections'
import { BIDataPaneSection } from 'products/business_intelligence/frontend/BIDataPaneSection'
import { BIDataSourcePicker } from 'products/business_intelligence/frontend/BIDataSourcePicker'
import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'
import { BIHierarchySection } from 'products/business_intelligence/frontend/BIHierarchySection'
import { BISourceContext } from 'products/business_intelligence/frontend/BISourceContext'

import { BIMemberAliasesModal } from '../BIMemberAliasesModal'
import { biSceneLogic } from '../biSceneLogic'
import { biSourcePreviewLogic } from '../biSourcePreviewLogic'
import { BISourcePreviewModal } from '../BISourcePreviewModal'
import { BIConnectionSelector } from './BIConnectionSelector'

/** Lists the selected table's fields as dimensions and measures, ready to drag onto shelves. */
export function BIDataPane({ tabId }: { tabId: string }): JSX.Element {
    const {
        config,
        allTables,
        databaseConnectionId,
        dataPaneFields,
        dataPaneFieldsLoading,
        dataPaneFieldsError,
        dataPaneSearch,
        filteredDataPaneFields,
    } = useValues(biEditorLogic)
    const { editCalculatedField, hydrateTableFields, setDataPaneSearch } = useActions(biEditorLogic)
    const { worksheet } = useValues(biSceneLogic({ tabId }))
    const { open } = useActions(biSourcePreviewLogic({ tabId }))

    const hasFields = dataPaneFields.dimensions.length > 0 || dataPaneFields.measures.length > 0
    const hasMatches = filteredDataPaneFields.dimensions.length > 0 || filteredDataPaneFields.measures.length > 0
    const sourceTable =
        !config.source?.connectionId && !databaseConnectionId
            ? allTables.find((table) => table.name === config.source?.table)
            : undefined

    return (
        <div className="flex min-h-0 flex-1 flex-col">
            <BISourcePreviewModal tabId={tabId} />
            <BIMemberAliasesModal tabId={tabId} />
            <div className="flex flex-col gap-1.5 p-2">
                <BIConnectionSelector tabId={tabId} />
                <BIDataSourcePicker />
                <LemonButton
                    size="xsmall"
                    onClick={() => open(worksheet)}
                    disabledReason={!config.source ? 'Select a data source first' : undefined}
                    data-attr="bi-source-view-data"
                >
                    View source data
                </LemonButton>
                {sourceTable && <BISourceContext table={sourceTable} />}
                {config.source ? (
                    <LemonInput
                        type="search"
                        size="xsmall"
                        value={dataPaneSearch}
                        onChange={setDataPaneSearch}
                        placeholder="Search fields"
                        aria-label="Search fields"
                    />
                ) : null}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-1 pb-2">
                {!config.source ? (
                    <p className="px-2 text-xs text-secondary">Select a table to list its fields.</p>
                ) : dataPaneFieldsLoading && !hasFields ? (
                    <div className="flex items-center gap-2 px-2 text-xs text-secondary">
                        <Spinner /> Loading fields
                    </div>
                ) : dataPaneFieldsError ? (
                    <div className="flex flex-col items-start gap-2 px-2 text-xs text-secondary">
                        <span>Couldn't load fields for this table.</span>
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            loading={dataPaneFieldsLoading}
                            onClick={() => config.source && hydrateTableFields([config.source.table])}
                        >
                            Retry
                        </LemonButton>
                    </div>
                ) : !hasFields ? (
                    <p className="px-2 text-xs text-secondary">No dimensions or measures on this table.</p>
                ) : !hasMatches ? (
                    <p className="px-2 text-xs text-secondary">No matching fields in this table</p>
                ) : (
                    <>
                        <BIDataPaneSection
                            title="Dimensions"
                            fields={filteredDataPaneFields.dimensions}
                            measure={false}
                            emptyText="No matching dimensions"
                        />
                        <BIDataPaneSection
                            title="Measures"
                            fields={filteredDataPaneFields.measures}
                            measure
                            emptyText={
                                dataPaneSearch
                                    ? 'No matching measures'
                                    : 'No measures listed. Add a dimension to Rows, then choose Convert to measure from its menu.'
                            }
                        />
                    </>
                )}
                {config.source && !dataPaneFieldsError && (
                    <LemonButton
                        icon={<IconPlus />}
                        size="xsmall"
                        fullWidth
                        onClick={() => editCalculatedField()}
                        data-attr="bi-editor-add-calculated-measure"
                    >
                        Add calculated field
                    </LemonButton>
                )}
                {config.source && !dataPaneFieldsError ? <BIHierarchySection tabId={tabId} /> : null}
                {config.source && !dataPaneFieldsError ? <BIConnections /> : null}
            </div>
        </div>
    )
}
