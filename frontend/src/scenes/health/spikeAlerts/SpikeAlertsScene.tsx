import { useActions, useValues } from 'kea'

import { IconMagicWand, IconRefresh, IconTrending } from '@posthog/icons'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { IconTrendingDown } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import type { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { useOpenAi } from 'scenes/max/useOpenAi'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { FlatSpikeRow } from './spikeAlertsSceneLogic'
import { spikeAlertsSceneLogic } from './spikeAlertsSceneLogic'

function ExplainSpikeButton({
    row,
    onExplain,
}: {
    row: FlatSpikeRow
    onExplain: (prompt: string) => void
}): JSX.Element {
    const direction = row.z_score < 0 ? 'decrease' : 'spike'
    const prompt = `Explain this usage ${direction}: the metric "${row.usage_key}" went from a weekday average of ${row.weekday_average} to ${row.value} on ${row.spike_date}.`
    return (
        <LemonButton
            size="small"
            type="stealth"
            icon={<IconMagicWand className="size-3" />}
            onClick={() => onExplain(prompt)}
            tooltip="Ask PostHog AI to explain this spike"
            className="text-xs font-normal text-default"
        >
            Explain
        </LemonButton>
    )
}

function buildColumns(onExplain: (prompt: string) => void): LemonTableColumns<FlatSpikeRow> {
    return [
        {
            title: 'Detected',
            dataIndex: 'detected_at',
            sorter: (a, b) => new Date(a.detected_at).getTime() - new Date(b.detected_at).getTime(),
            render: (detected_at) =>
                humanFriendlyDetailedTime(detected_at as string, 'MMM D, YYYY', 'h:mm:ss A', {
                    timestampStyle: 'absolute',
                }),
        },
        {
            title: 'Metric',
            key: 'metric',
            render: function Render(_, row) {
                return (
                    <div className="flex items-center gap-2">
                        {row.z_score < 0 ? (
                            <IconTrendingDown className="text-success size-4 shrink-0" />
                        ) : (
                            <IconTrending className="text-danger size-4 shrink-0" />
                        )}
                        <span>{row.usage_key}</span>
                    </div>
                )
            },
        },
        {
            title: 'Value',
            dataIndex: 'value',
        },
        {
            title: 'Avg',
            dataIndex: 'weekday_average',
        },
        {
            key: 'explain',
            width: 0,
            render: function Render(_, row) {
                return <ExplainSpikeButton row={row} onExplain={onExplain} />
            },
        },
    ]
}

export function SpikeAlertsScene(): JSX.Element {
    const { filteredAlerts, spikeAlertsLoading, searchTerm, spikeAlerts } = useValues(spikeAlertsSceneLogic)
    const { setSearchTerm, loadSpikeAlerts } = useActions(spikeAlertsSceneLogic)
    const { openSupportForm } = useActions(supportLogic)
    const { openAi } = useOpenAi()

    const columns = buildColumns(openAi)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Spike alerts"
                description={null}
                resourceType={{ type: 'health', forceIcon: <IconTrending /> }}
            />
            <p className="text-sm mb-4">
                Monitor spike alerts. Notice something unusual?{' '}
                <span className="cursor-pointer underline" onClick={() => openSupportForm({ kind: 'support' })}>
                    Reach out to us
                </span>
                .
            </p>
            <div className="space-y-4">
                <SceneStickyBar showBorderBottom={false}>
                    <div className="flex gap-2 items-center justify-between">
                        <LemonInput
                            className="flex-1"
                            value={searchTerm}
                            onChange={setSearchTerm}
                            type="search"
                            placeholder="Search by metric..."
                        />
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconRefresh className="size-4" />}
                            disabledReason={spikeAlertsLoading ? 'Refreshing...' : undefined}
                            onClick={() => loadSpikeAlerts()}
                        >
                            {spikeAlertsLoading ? 'Refreshing...' : 'Refresh'}
                        </LemonButton>
                    </div>
                </SceneStickyBar>
                {spikeAlertsLoading && spikeAlerts === null ? (
                    <div className="space-y-3">
                        <LemonSkeleton className="h-8" />
                        <LemonSkeleton className="h-20" />
                        <LemonSkeleton className="h-20" />
                    </div>
                ) : filteredAlerts.length === 0 ? (
                    <div className="text-center text-muted p-8">No spike alerts detected. Check back later.</div>
                ) : (
                    <LemonTable
                        dataSource={filteredAlerts}
                        columns={columns}
                        rowKey="rowKey"
                        loading={spikeAlertsLoading}
                        defaultSorting={{ columnKey: 'detected_at', order: -1 }}
                        noSortingCancellation
                    />
                )}
            </div>
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: SpikeAlertsScene,
    logic: spikeAlertsSceneLogic,
}
