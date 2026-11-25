import { useActions, useValues } from 'kea'

import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Item,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Skeleton,
} from '@posthog/quill'

import { UsageScanWindow } from '../components/UsageScanWindow'
import { usageLogic } from '../usageLogic'
import { GovernanceSourcesTable } from './GovernanceSourcesTable'
import { GovernanceTopicsTable } from './GovernanceTopicsTable'

const SKELETON_ROWS = 4

function RecomputeButton({ size, dataAttr }: { size?: 'sm'; dataAttr: string }): JSX.Element {
    const { recomputeDisabledReason, recomputedLoading } = useValues(usageLogic)
    const { recompute } = useActions(usageLogic)
    return (
        <Button
            variant="outline"
            size={size}
            onClick={recompute}
            loading={recomputedLoading}
            disabledReason={recomputeDisabledReason}
            data-attr={dataAttr}
        >
            Run a new scan
        </Button>
    )
}

function NoScanYet(): JSX.Element {
    const { newestScan, scanRunning } = useValues(usageLogic)
    return (
        <div className="flex flex-col gap-3">
            {newestScan?.status === 'error' && (
                <Item variant="outline" tone="warning">
                    <ItemContent>
                        <ItemTitle>The last scan failed.</ItemTitle>
                        {newestScan.error_message && <ItemDescription>{newestScan.error_message}</ItemDescription>}
                    </ItemContent>
                </Item>
            )}
            <Empty>
                <EmptyHeader>
                    <EmptyTitle>{scanRunning ? 'A usage scan is running' : 'No usage scan yet'}</EmptyTitle>
                    <EmptyDescription>
                        {scanRunning
                            ? 'Results appear here when it finishes.'
                            : 'A scan runs every week, or you can start one now.'}
                    </EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <RecomputeButton dataAttr="data-catalog-governance-recompute" />
                </EmptyContent>
            </Empty>
        </div>
    )
}

function GovernanceContent(): JSX.Element {
    const { latest, latestLoadFailed, usageUnavailable, scanRunning, newestScan } = useValues(usageLogic)

    if (usageUnavailable) {
        return (
            <Item variant="outline" tone="info">
                <ItemContent>
                    <ItemDescription>Usage scans aren't available for this project.</ItemDescription>
                </ItemContent>
            </Item>
        )
    }
    if (latestLoadFailed) {
        return (
            <Item variant="outline" tone="destructive">
                <ItemContent>
                    <ItemDescription>
                        Couldn't load the usage scan. Refresh the page, and if it keeps happening contact support.
                    </ItemDescription>
                </ItemContent>
            </Item>
        )
    }
    if (latest === null) {
        return (
            <div className="flex flex-col gap-2" aria-busy="true">
                {Array.from({ length: SKELETON_ROWS }, (_, index) => (
                    <Skeleton key={index} className="h-12 w-full" />
                ))}
            </div>
        )
    }
    if (latest === 'none') {
        return <NoScanYet />
    }

    return (
        <div className="flex flex-col gap-6">
            {scanRunning && (
                <Item variant="outline" tone="info">
                    <ItemContent>
                        <ItemDescription>
                            A new scan is running. These results are from the last finished scan.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}
            {newestScan?.status === 'error' && (
                <Item variant="outline" tone="warning">
                    <ItemContent>
                        <ItemTitle>The last scan failed, so these results are from an earlier scan.</ItemTitle>
                        {newestScan.error_message && <ItemDescription>{newestScan.error_message}</ItemDescription>}
                    </ItemContent>
                </Item>
            )}
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <UsageScanWindow scan={latest} />
                    <RecomputeButton size="sm" dataAttr="data-catalog-governance-rescan" />
                </div>
                <div className="@container">
                    <div className="grid grid-cols-1 items-start gap-6 @4xl:grid-cols-2">
                        <GovernanceTopicsTable />
                        <GovernanceSourcesTable />
                    </div>
                </div>
            </div>
        </div>
    )
}

export function CatalogGovernanceSection(): JSX.Element {
    return (
        <section aria-label="Governance" className="flex flex-col gap-3" data-attr="data-catalog-governance">
            <GovernanceContent />
        </section>
    )
}
