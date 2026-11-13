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

const COLUMNS: DataTableProps<TopicClusterApi, unknown>['columns'] = [
    {
        accessorKey: 'title',
        header: 'Topic',
        enableSorting: false,
        cell: ({ row }) => (
            <Text size="xs" weight="semibold" className="block max-w-64 min-w-40 truncate" title={row.original.title}>
                {row.original.title}
            </Text>
        ),
    },
    { accessorKey: 'people', header: 'People', meta: { align: 'right' } },
    { accessorKey: 'session_count', header: 'Sessions', meta: { align: 'right' } },
    {
        id: 'coverage',
        header: () => (
            <GovernanceColumnHeader
                label="Catalog coverage"
                tooltip="The number is how many sessions looked for a metric in the catalog. Each bar splits those sessions by what they found: a metric that fits, a table but no metric, or nothing. Hover a part of the bar to see its sessions. Each session counts once, and a metric comes first."
            />
        ),
        meta: { expand: true },
        cell: ({ row }) => <TopicCoverageBar coverage={row.original.coverage} />,
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
