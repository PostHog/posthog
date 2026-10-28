import { useActions, useValues } from 'kea'

import { IconPlus, IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { llmEvaluationsLogic } from '../llmEvaluationsLogic'
import { EvaluationAttentionPills } from './EvaluationAttentionPills'
import { EvaluationCreateSlot } from './EvaluationCreateSlot'
import { EvaluationDirectoryTiles } from './EvaluationDirectoryTiles'
import { EvaluationResultActions } from './EvaluationResultActions'
import { EvaluationResultCell } from './EvaluationResultCell'
import { EvaluationResultDrawer } from './EvaluationResultDrawer'
import { EvaluationResultNameCell } from './EvaluationResultNameCell'
import { EvaluationResultTrendCell } from './EvaluationResultTrendCell'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

export function EvaluationResultsTable(): JSX.Element {
    const {
        tableRows,
        rows,
        buckets,
        search,
        attentionFilter,
        configById,
        few,
        overviewLoading,
        overviewFailure,
        directoryTiles,
    } = useValues(evaluationsOverviewLogic)
    const { setSearch } = useActions(evaluationsOverviewLogic)
    const { openCreateDirectory } = useActions(llmEvaluationsLogic)

    const columns: LemonTableColumns<EvaluationResultApi> = [
        {
            title: 'Evaluation',
            key: 'name',
            render: (_, row) => <EvaluationResultNameCell row={row} />,
            sorter: (a, b) => a.name.localeCompare(b.name),
        },
        {
            title: 'Result',
            key: 'result',
            render: (_, row) => <EvaluationResultCell row={row} />,
            // Sorts by how many results were graded, since results of different types share no scale.
            sorter: (a, b) => a.gradedCount - b.gradedCount,
        },
        {
            title: 'Trend',
            key: 'trend',
            // Under about 520px the change moves under the result instead.
            className: 'hidden @min-[32.5rem]:table-cell',
            tooltip: 'Change against the previous period of the same length, and the trend within this range',
            width: 0,
            render: (_, row) => <EvaluationResultTrendCell row={row} buckets={buckets} />,
        },
        {
            title: 'Created by',
            key: 'created_by',
            className: 'hidden @min-[40rem]:table-cell whitespace-nowrap',
            render: (_, row) => {
                const user = configById.get(row.id)?.created_by
                return user ? (
                    <ProfilePicture user={user} size="md" showName />
                ) : row.createdBy ? (
                    <ProfilePicture name={row.createdBy} size="md" showName />
                ) : (
                    <span className="text-secondary">-</span>
                )
            },
        },
        {
            key: 'actions',
            width: 0,
            render: (_, row) => {
                const config = configById.get(row.id)
                return config ? <EvaluationResultActions config={config} /> : null
            },
        },
    ]

    return (
        <div className="@container flex flex-col gap-3">
            <EvaluationDirectoryTiles />
            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    type="search"
                    size="small"
                    className="flex-1 min-w-48"
                    prefix={<IconSearch />}
                    placeholder="Search evaluations"
                    value={search}
                    onChange={setSearch}
                    data-attr="evaluation-overview-table-search"
                />
                {directoryTiles.length === 0 && (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Evaluation}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            icon={<IconPlus />}
                            onClick={() => openCreateDirectory()}
                            data-attr="create-evaluation-directory-button"
                        >
                            New directory
                        </LemonButton>
                    </AccessControlAction>
                )}
                <EvaluationAttentionPills />
            </div>
            <LemonTable
                columns={columns}
                dataSource={tableRows}
                loading={overviewLoading}
                rowKey="id"
                // Each row draws a trend chart, so a long list renders one page at a time.
                pagination={{ pageSize: 50 }}
                nouns={['evaluation', 'evaluations']}
                footer={
                    few && (
                        <div className="p-2">
                            <EvaluationCreateSlot className="w-full py-3" />
                        </div>
                    )
                }
                emptyState={
                    overviewFailure
                        ? "Results didn't load. Try again above."
                        : attentionFilter || search
                          ? 'No evaluations match this search or filter.'
                          : 'No evaluations in this scope yet.'
                }
            />
            <div className="text-xs text-secondary pb-4">{`Showing ${tableRows.length} of ${rows.length} evaluations`}</div>
            <EvaluationResultDrawer />
        </div>
    )
}
