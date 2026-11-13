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
    Text,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import type { UsageSnapshotApi } from '../generated/api.schemas'
import { usageLogic } from '../usageLogic'
import { GovernanceProposedTable } from './GovernanceProposedTable'
import { GovernanceSourcesTable } from './GovernanceSourcesTable'
import { GovernanceTopicsTable } from './GovernanceTopicsTable'

const SKELETON_ROWS = 4

function RecomputeButton(): JSX.Element {
    const { recomputeDisabledReason, recomputedLoading } = useValues(usageLogic)
    const { recompute } = useActions(usageLogic)
    return (
        <Button
            variant="outline"
            onClick={recompute}
            loading={recomputedLoading}
            disabledReason={recomputeDisabledReason}
            data-attr="data-catalog-usage-recompute"
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
                    <RecomputeButton />
                </EmptyContent>
            </Empty>
        </div>
    )
}

function ScanWindow({ scan }: { scan: UsageSnapshotApi }): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<p className="m-0" />}>
            Usage from <TZLabel time={scan.window_start} /> to <TZLabel time={scan.window_end} />
            {scan.computed_at && (
                <>
                    , scanned <TZLabel time={scan.computed_at} />
                </>
            )}
            .
        </Text>
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
                <ScanWindow scan={latest} />
                <div className="@container">
                    <div className="grid grid-cols-1 items-start gap-6 @4xl:grid-cols-2">
                        <GovernanceTopicsTable />
                        <GovernanceSourcesTable />
                    </div>
                </div>
            </div>
            <GovernanceProposedTable />
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
