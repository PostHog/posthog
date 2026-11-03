import { BindLogic, useActions, useValues } from 'kea'

import { IconEllipsis, IconGear } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonMenu,
    LemonMenuItems,
    LemonSkeleton,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Spinner,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { urls } from 'scenes/urls'

import { CheckEditorModal } from 'products/data_quality/frontend/CheckEditorModal'
import { dataQualityCheckEditorLogic } from 'products/data_quality/frontend/dataQualityCheckEditorLogic'
import {
    NEW_CHECK_ACTION_ID,
    dataQualityOverviewLogic,
} from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'
import { overviewCheckEditorProps } from 'products/data_quality/frontend/overview/overviewCheckEditorProps'
import { RunAllBanners } from 'products/data_quality/frontend/overview/RunAllBanners'
import { SuggestedCertificationsTable } from 'products/warehouse_suggestions/frontend/components/SuggestedCertificationsTable'

import { CatalogTableRow, TABLES_FILTERS, TablesFilter } from '../catalogTableRows'
import { catalogTablesLogic } from '../catalogTablesLogic'
import { certificationsLogic } from '../certificationsLogic'
import { certificationStatusTag } from '../certificationStatusTag'
import { compareText } from '../common'
import { NewCertificationModal } from '../components/NewCertificationModal'
import { TableChecksPanel } from '../components/TableChecksPanel'
import { confirmRevokeCertification } from '../confirmRevokeCertification'

const FILTER_LABELS: Record<TablesFilter, string> = {
    failing: 'Failing checks',
    no_checks: 'No checks',
    proposed: 'Proposed',
    certified: 'Certified',
    deprecated: 'Deprecated',
    all: 'All',
}

const WIDE_ONLY_COLUMN = 'hidden @2xl/main-content:table-cell'

const EMPTY_CELL = <span className="text-secondary">-</span>

export function TablesTab(): JSX.Element {
    const { filteredRows, rowsLoaded, rowsError, filterCounts, activeFilter, search, expandedRowKeys } =
        useValues(catalogTablesLogic)
    const { setSearch, setFilter, toggleRowExpanded, runTableChecks, proposeCertification, revealCertification } =
        useActions(catalogTablesLogic)
    const { checks, startingRun, isRunning, runTarget, runningSubjectKey, lastActionCheckId } =
        useValues(dataQualityOverviewLogic)
    const { runChecks, loadOverview, setLastActionCheck } = useActions(dataQualityOverviewLogic)
    const { actionsInFlight } = useValues(certificationsLogic)
    const { certifyCertification, deprecateCertification, revokeCertification, suggestionAccepted } =
        useActions(certificationsLogic)
    const { loadDatabase } = useActions(databaseTableListLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const editorProps = overviewCheckEditorProps({ lastActionCheckId, loadOverview, runChecks })
    const { openEditor } = useActions(dataQualityCheckEditorLogic(editorProps))

    const anyRunActive = startingRun || isRunning
    const runningAll = anyRunActive && runTarget?.kind === 'all'

    const addCheck = (): void => {
        setLastActionCheck(null)
        openEditor(null, null)
    }

    if (!rowsLoaded && rowsError) {
        return (
            <LemonBanner
                type="error"
                action={{
                    children: 'Retry',
                    onClick: () => {
                        loadDatabase()
                        loadOverview()
                    },
                }}
            >
                Couldn't load your tables. Try again.
            </LemonBanner>
        )
    }

    if (!rowsLoaded) {
        return (
            <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-2">
                    <LemonSkeleton className="h-8 w-64 max-w-full" />
                    <LemonSkeleton className="h-8 w-80 max-w-full" />
                </div>
                <LemonSkeleton.Row repeat={5} fade />
            </div>
        )
    }

    const rowMenuItems = (row: CatalogTableRow): LemonMenuItems => {
        const certification = row.certification
        const inFlight = certification ? !!actionsInFlight[certification.id] : false
        const runChecksItem = {
            label: 'Run checks',
            onClick: () => runTableChecks(row),
            disabledReason: !row.checkGroup
                ? 'This table has no checks yet'
                : anyRunActive
                  ? 'Checks are already running'
                  : undefined,
        }
        if (!row.certificationTarget) {
            return [runChecksItem]
        }
        if (!certification) {
            return [
                runChecksItem,
                {
                    items: [{ label: 'Propose certification', onClick: () => proposeCertification(row) }],
                },
            ]
        }
        const working = inFlight ? 'Working' : undefined
        return [
            runChecksItem,
            {
                items: [
                    certification.status !== 'certified' && {
                        label: 'Certify',
                        onClick: () => certifyCertification(certification.id),
                        disabledReason: working,
                    },
                    certification.status !== 'deprecated' && {
                        label: 'Deprecate',
                        onClick: () => deprecateCertification(certification.id),
                        disabledReason: working,
                    },
                    {
                        label: 'Revoke',
                        status: 'danger',
                        onClick: () =>
                            confirmRevokeCertification(certification, () => revokeCertification(certification.id)),
                        disabledReason: working,
                    },
                ],
            },
        ]
    }

    const checksSummary = (row: CatalogTableRow): JSX.Element | null => {
        const group = row.checkGroup
        if (!group) {
            return null
        }
        if (runningSubjectKey === group.subjectKey) {
            return (
                <span className="flex items-center gap-1 text-secondary whitespace-nowrap">
                    <Spinner />
                    <span>Running</span>
                </span>
            )
        }
        if (row.failingCheckCount > 0) {
            return <LemonTag type="danger">{`${row.failingCheckCount} failing`}</LemonTag>
        }
        const passing = group.checks.filter((check) => check.last_status === 'passed').length
        return <span className="whitespace-nowrap">{`${passing}/${group.checks.length} passing`}</span>
    }

    const trustTag = (row: CatalogTableRow): JSX.Element | null => {
        if (!row.certification) {
            return null
        }
        const tag = certificationStatusTag(row.certification)
        return <LemonTag type={tag.type}>{tag.label}</LemonTag>
    }

    const freshness = (row: CatalogTableRow): JSX.Element | null =>
        row.refreshedAt ? <TZLabel time={row.refreshedAt} /> : null

    const columns: LemonTableColumns<CatalogTableRow> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, row) => (
                <div className="flex flex-col min-w-0">
                    <LemonTableLink
                        to={row.detailUrl ?? undefined}
                        title={<span className="truncate">{row.name}</span>}
                        description={<span>{row.origin}</span>}
                        truncateTitle
                    />
                    <div className="flex flex-wrap items-center gap-2 pb-1 empty:hidden @2xl/main-content:hidden">
                        {checksSummary(row)}
                        {trustTag(row)}
                        {freshness(row)}
                    </div>
                </div>
            ),
            sorter: (a, b) => compareText(a.name, b.name),
        },
        {
            title: 'Checks',
            key: 'checks',
            className: WIDE_ONLY_COLUMN,
            render: (_, row) => checksSummary(row) ?? EMPTY_CELL,
            sorter: (a, b) => a.failingCheckCount - b.failingCheckCount,
        },
        {
            title: 'Trust',
            key: 'trust',
            className: WIDE_ONLY_COLUMN,
            render: (_, row) => trustTag(row) ?? EMPTY_CELL,
            sorter: (a, b) => compareText(a.certification?.status, b.certification?.status),
        },
        {
            title: 'Freshness',
            key: 'freshness',
            className: WIDE_ONLY_COLUMN,
            render: (_, row) => freshness(row) ?? EMPTY_CELL,
            sorter: (a, b) => compareText(a.refreshedAt, b.refreshedAt),
        },
        {
            key: 'actions',
            width: 0,
            render: (_, row) => (
                <LemonMenu items={rowMenuItems(row)}>
                    <LemonButton
                        size="small"
                        icon={<IconEllipsis />}
                        aria-label={`Actions for ${row.name}`}
                        data-attr="data-catalog-tables-row-actions"
                    />
                </LemonMenu>
            ),
        },
    ]

    return (
        <BindLogic logic={dataQualityCheckEditorLogic} props={editorProps}>
            <div className="flex flex-col gap-3">
                {featureFlags[FEATURE_FLAGS.WAREHOUSE_SUGGESTIONS] && (
                    <SuggestedCertificationsTable
                        onAccepted={() => suggestionAccepted()}
                        onViewAccepted={(suggestion) => {
                            const certificationId = suggestion.created_asset?.certification_id
                            if (typeof certificationId === 'string') {
                                revealCertification(certificationId)
                            }
                        }}
                    />
                )}
                <div className="flex flex-wrap items-center gap-2">
                    <LemonInput
                        type="search"
                        size="small"
                        placeholder="Search tables"
                        value={search}
                        onChange={setSearch}
                        className="flex-1 min-w-40 max-w-64"
                    />
                    <div className="flex flex-wrap items-center gap-2 ml-auto">
                        <LemonButton
                            type="tertiary"
                            size="small"
                            icon={<IconGear />}
                            to={urls.settings('environment-data-quality')}
                            tooltip="Data quality settings"
                            aria-label="Data quality settings"
                            data-attr="data-catalog-tables-settings"
                        />
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => runChecks({ kind: 'all' })}
                            loading={runningAll}
                            disabledReason={
                                checks.length === 0
                                    ? 'There are no checks to run yet'
                                    : anyRunActive && !runningAll
                                      ? 'Checks are already running'
                                      : undefined
                            }
                            data-attr="data-catalog-tables-run-all"
                        >
                            Run all checks
                        </LemonButton>
                        <LemonButton
                            id={NEW_CHECK_ACTION_ID}
                            type="primary"
                            size="small"
                            onClick={addCheck}
                            data-attr="data-catalog-tables-new-check"
                        >
                            New check
                        </LemonButton>
                    </div>
                </div>
                <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Filter tables">
                    {TABLES_FILTERS.map((filter) => (
                        <LemonButton
                            key={filter}
                            type={activeFilter === filter ? 'primary' : 'secondary'}
                            size="xsmall"
                            aria-pressed={activeFilter === filter}
                            onClick={() => setFilter(filter)}
                            data-attr={`data-catalog-tables-filter-${filter}`}
                        >
                            <span>{FILTER_LABELS[filter]}</span>
                            <span className="ml-1 text-secondary">{filterCounts[filter]}</span>
                        </LemonButton>
                    ))}
                </div>

                <RunAllBanners />

                <LemonTable
                    data-attr="data-catalog-tables-table"
                    dataSource={filteredRows}
                    rowKey="key"
                    columns={columns}
                    size="small"
                    nouns={['table', 'tables']}
                    expandable={{
                        expandedRowRender: (row) => <TableChecksPanel row={row} />,
                        isRowExpanded: (row) => expandedRowKeys.includes(row.key),
                        onRowExpand: (row) => toggleRowExpanded(row.key),
                        onRowCollapse: (row) => toggleRowExpanded(row.key),
                    }}
                    emptyState={
                        <div className="flex flex-wrap items-center gap-2">
                            <span>No tables match these filters.</span>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => {
                                    setFilter('all')
                                    setSearch('')
                                }}
                            >
                                Show all tables
                            </LemonButton>
                        </div>
                    }
                />

                <CheckEditorModal />
                <NewCertificationModal />
            </div>
        </BindLogic>
    )
}
