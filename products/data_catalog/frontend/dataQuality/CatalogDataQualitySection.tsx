import { BindLogic, useActions, useValues } from 'kea'

import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle, Skeleton, Text } from '@posthog/quill'

import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { ModelsOverviewErrorCallout } from 'products/data_modeling/frontend/ModelsOverviewErrorCallout'
import { dataQualityCheckEditorLogic } from 'products/data_quality/frontend/dataQualityCheckEditorLogic'
import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'
import { overviewCheckEditorProps } from 'products/data_quality/frontend/overview/overviewCheckEditorProps'
import { QuillRunAllBanners } from 'products/data_quality/frontend/overview/QuillRunAllBanners'
import { QuillCheckEditorDialog } from 'products/data_quality/frontend/QuillCheckEditorDialog'

import { CatalogDataQualityActions } from './CatalogDataQualityActions'
import { catalogDataQualityLogic } from './catalogDataQualityLogic'
import { CatalogDataQualityToolbar } from './CatalogDataQualityToolbar'
import { CatalogTableChecksGroup } from './CatalogTableChecksGroup'

const SKELETON_ROWS = 4

function ShowAllTablesButton(): JSX.Element {
    const { showAllTables } = useActions(catalogDataQualityLogic)
    return (
        <Button variant="outline" size="sm" onClick={showAllTables} data-attr="data-catalog-quality-show-all">
            Show all tables
        </Button>
    )
}

function TableFilterNote({ tableName }: { tableName: string }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2">
            <Text size="sm">
                Checks for <span className="font-medium">{tableName}</span>
            </Text>
            <ShowAllTablesButton />
        </div>
    )
}

function NoTables({ tableFilter }: { tableFilter: string | null }): JSX.Element {
    return (
        <Empty>
            <EmptyHeader>
                <EmptyTitle>{tableFilter ? `No table named ${tableFilter}` : 'No checks yet'}</EmptyTitle>
                <EmptyDescription>
                    {tableFilter
                        ? 'It may have been renamed or deleted.'
                        : 'Add a check with New check to watch a table for bad data.'}
                </EmptyDescription>
            </EmptyHeader>
        </Empty>
    )
}

function SectionFilters(): JSX.Element | null {
    const { tableFilter, rowsLoaded, checkedRows } = useValues(catalogDataQualityLogic)
    if (tableFilter) {
        return <TableFilterNote tableName={tableFilter} />
    }
    if (!rowsLoaded || checkedRows.length === 0) {
        return null
    }
    return <CatalogDataQualityToolbar />
}

function NoMatchingTables(): JSX.Element {
    const { clearFilters } = useActions(catalogDataQualityLogic)
    return (
        <Empty className="py-8">
            <EmptyHeader>
                <EmptyTitle>No tables match these filters</EmptyTitle>
            </EmptyHeader>
            <EmptyContent>
                <Button variant="outline" onClick={clearFilters} data-attr="data-catalog-quality-clear-filters">
                    Clear filters
                </Button>
            </EmptyContent>
        </Empty>
    )
}

function QualityContent(): JSX.Element {
    const { checkedRows, shownRows, rowsLoaded, rowsError, tableFilter, expandedTableKeys } =
        useValues(catalogDataQualityLogic)
    const { loadDatabase } = useActions(databaseTableListLogic)
    const { loadOverview } = useActions(dataQualityOverviewLogic)

    if (!rowsLoaded && rowsError) {
        return (
            <ModelsOverviewErrorCallout
                message="Your checks could not be loaded. Try again, and if it keeps failing, refresh the page."
                onRetry={() => {
                    loadDatabase({ shallow: true })
                    loadOverview()
                }}
                dataAttr="data-catalog-quality-error"
            />
        )
    }
    if (!rowsLoaded) {
        return (
            <div className="flex flex-col gap-2" aria-busy="true">
                {Array.from({ length: SKELETON_ROWS }, (_, index) => (
                    <Skeleton key={index} className="h-12 w-full" />
                ))}
            </div>
        )
    }
    if (checkedRows.length === 0) {
        return <NoTables tableFilter={tableFilter} />
    }
    return (
        <div className="flex flex-col gap-2">
            {shownRows.length === 0 && <NoMatchingTables />}
            {shownRows.map((row) => (
                <CatalogTableChecksGroup
                    key={row.key}
                    row={row}
                    collapsible={!tableFilter}
                    expanded={!!tableFilter || expandedTableKeys.includes(row.key)}
                />
            ))}
        </div>
    )
}

export function CatalogDataQualitySection(): JSX.Element {
    const { lastActionCheckId } = useValues(dataQualityOverviewLogic)
    const { loadOverview, runChecks } = useActions(dataQualityOverviewLogic)
    const editorProps = overviewCheckEditorProps({ lastActionCheckId, loadOverview, runChecks })

    return (
        <BindLogic logic={dataQualityCheckEditorLogic} props={editorProps}>
            <section aria-label="Data quality" className="flex flex-col gap-3" data-attr="data-catalog-quality">
                <div className="flex flex-wrap items-center gap-2">
                    <SectionFilters />
                    <CatalogDataQualityActions />
                </div>
                <QuillRunAllBanners />
                <QualityContent />
            </section>
            <QuillCheckEditorDialog />
        </BindLogic>
    )
}
