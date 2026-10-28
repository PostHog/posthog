import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonModal, Spinner } from '@posthog/lemon-ui'

import { biHierarchyLogic } from './biHierarchyLogic'

export function BIHierarchyImportModal({ tabId }: { tabId: string }): JSX.Element {
    const logic = biHierarchyLogic({ tabId })
    const {
        importOpen,
        search,
        page,
        worksheets,
        worksheetsLoading,
        hierarchySource,
        hierarchySourceLoading,
        importHierarchies,
        importError,
        config,
        selectedWorksheetId,
    } = useValues(logic)
    const { closeImport, setSearch, setPage, loadHierarchySource, importHierarchy, retryImport } = useActions(logic)
    return (
        <LemonModal isOpen={importOpen} onClose={closeImport} title="Import a hierarchy" width={600}>
            <div className="flex flex-col gap-3">
                <p className="m-0 text-secondary">
                    Copy a named hierarchy from a saved worksheet using the same data source.
                </p>
                <LemonInput
                    type="search"
                    aria-label="Search worksheets for hierarchies"
                    placeholder="Search saved worksheets"
                    value={search}
                    onChange={setSearch}
                />
                {importError ? (
                    <LemonBanner type="error">
                        Couldn't load worksheets or hierarchies.{' '}
                        <LemonButton
                            size="xsmall"
                            onClick={retryImport}
                            loading={worksheetsLoading || hierarchySourceLoading}
                        >
                            Retry
                        </LemonButton>
                    </LemonBanner>
                ) : null}
                {worksheetsLoading ? (
                    <Spinner />
                ) : worksheets?.results.length ? (
                    <div className="max-h-60 overflow-y-auto">
                        {worksheets.results.map((worksheet) => (
                            <LemonButton
                                key={worksheet.id}
                                fullWidth
                                size="small"
                                active={hierarchySource?.id === worksheet.id}
                                loading={hierarchySourceLoading && selectedWorksheetId === worksheet.id}
                                disabledReason={hierarchySourceLoading ? 'Loading hierarchy definitions' : undefined}
                                onClick={() => loadHierarchySource(worksheet.id)}
                            >
                                <span className="truncate">
                                    {worksheet.name || worksheet.derived_name || 'Untitled worksheet'}
                                </span>
                            </LemonButton>
                        ))}
                    </div>
                ) : !importError ? (
                    <p className="m-0 text-secondary">No saved worksheets found.</p>
                ) : null}
                <div className="flex gap-2">
                    <LemonButton
                        size="small"
                        disabledReason={page === 0 || worksheetsLoading ? 'No previous page available' : undefined}
                        onClick={() => setPage(page - 1)}
                    >
                        Previous
                    </LemonButton>
                    <LemonButton
                        size="small"
                        disabledReason={!worksheets?.next || worksheetsLoading ? 'No next page available' : undefined}
                        onClick={() => setPage(page + 1)}
                    >
                        Next
                    </LemonButton>
                </div>
                {hierarchySourceLoading ? (
                    <Spinner />
                ) : hierarchySource ? (
                    <div className="border-t pt-3 space-y-2">
                        {importHierarchies.length ? (
                            importHierarchies.map((hierarchy) => (
                                <LemonButton
                                    key={hierarchy.id}
                                    fullWidth
                                    type="secondary"
                                    onClick={() => importHierarchy(hierarchy.id)}
                                    disabledReason={
                                        hierarchy.levels.some(
                                            (field) =>
                                                field.source.table !== config.source?.table ||
                                                (field.source.connectionId ?? null) !==
                                                    (config.source?.connectionId ?? null)
                                        )
                                            ? 'This hierarchy uses a different data source'
                                            : undefined
                                    }
                                >
                                    <span className="min-w-0 text-left">
                                        <span className="block truncate">{hierarchy.name}</span>
                                        <span className="block text-xs font-normal break-words">
                                            {hierarchy.levels.map((field) => field.name).join(' → ')}
                                        </span>
                                    </span>
                                </LemonButton>
                            ))
                        ) : (
                            <p className="m-0 text-secondary">This worksheet has no named hierarchies.</p>
                        )}
                    </div>
                ) : null}
            </div>
        </LemonModal>
    )
}
