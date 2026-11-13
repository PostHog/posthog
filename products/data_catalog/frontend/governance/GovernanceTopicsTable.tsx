import { useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import {
    DataTable,
    type DataTableProps,
    Heading,
    Item,
    ItemContent,
    ItemDescription,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import type { TopicClusterApi } from '../generated/api.schemas'
import { TopicCoverageBar } from '../tabs/TopicCoverageBar'
import { usageLogic } from '../usageLogic'
import { GovernanceColumnHeader } from './GovernanceColumnHeader'
import { GovernanceSectionFailed } from './GovernanceSectionFailed'
import { GovernanceTableEmpty } from './GovernanceTableEmpty'

const PAGE_SIZE = 6

// The judge step writes the adjusted runs, which tell the topics which sessions adapted a metric they read.
const AGENT_COUNTS_MISSING =
    'Coverage can miss metrics that agents adapted, because the agent query check failed in the last scan.'

// The topics come ranked, and sort buttons would widen a table that shares its row with the sources.
const COLUMNS: DataTableProps<TopicClusterApi, unknown>['columns'] = [
    {
        accessorKey: 'title',
        header: 'Topic',
        meta: { expand: true },
        enableSorting: false,
        cell: ({ row }) => (
            // Zero width keeps a long title out of the column's natural width, so it truncates instead of widening the table.
            <div className="min-w-24">
                <Text
                    size="xs"
                    weight="semibold"
                    className="block w-0 min-w-full truncate"
                    title={row.original.title}
                    render={<span />}
                >
                    {row.original.title}
                </Text>
            </div>
        ),
    },
    { accessorKey: 'people', header: 'People', meta: { align: 'right' }, enableSorting: false },
    { accessorKey: 'session_count', header: 'Sessions', meta: { align: 'right' }, enableSorting: false },
    {
        id: 'coverage',
        enableSorting: false,
        header: () => (
            <GovernanceColumnHeader
                label="Catalog coverage"
                tooltip="The number is how many sessions looked for a metric in the catalog. Each bar splits those sessions by what they found: a metric that fits, a table but no metric, or nothing. Hover a part of the bar to see its sessions. Each session counts once, and a metric comes first."
            />
        ),
        cell: ({ row }) => (
            <div className="w-36">
                <TopicCoverageBar coverage={row.original.coverage} />
            </div>
        ),
    },
]

export function GovernanceTopicsTable(): JSX.Element {
    const { topics, topicSessionsSummary, failureReasons } = useValues(usageLogic)
    return (
        <section className="flex min-w-0 flex-col gap-2" data-attr="data-catalog-usage-topics">
            <div className="flex min-h-6 items-center gap-1">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Top agent topics
                </Heading>
                {!failureReasons.topics && topicSessionsSummary && (
                    <Tooltip>
                        <TooltipTrigger render={<span className="inline-flex" />}>
                            <IconInfo className="text-muted-foreground" />
                        </TooltipTrigger>
                        <TooltipContent>{topicSessionsSummary}</TooltipContent>
                    </Tooltip>
                )}
            </div>
            {failureReasons.topics ? (
                <GovernanceSectionFailed reason={failureReasons.topics} />
            ) : (
                <>
                    {failureReasons.adjusted_runs && (
                        <Item variant="outline" tone="warning">
                            <ItemContent>
                                <ItemDescription>{AGENT_COUNTS_MISSING}</ItemDescription>
                            </ItemContent>
                        </Item>
                    )}
                    <DataTable
                        columns={COLUMNS}
                        data={topics}
                        getRowId={(topic) => topic.title}
                        pageSize={PAGE_SIZE}
                        size="sm"
                        fullWidth
                        empty={
                            <GovernanceTableEmpty>No agent session analyzed data in this window.</GovernanceTableEmpty>
                        }
                    />
                </>
            )}
        </section>
    )
}
