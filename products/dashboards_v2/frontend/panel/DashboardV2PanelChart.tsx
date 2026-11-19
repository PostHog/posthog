import { useEffect, useMemo, useState } from 'react'

import { ErrorBoundary } from '~/layout/ErrorBoundary/ErrorBoundary'

import { withDisplayDefaults } from '../charts/chartCommon'
import type { DataFrame } from '../charts/frame'
import { applyFrameTransforms, hiddenRefIds, incompleteFrames, incompleteMode } from '../charts/frames'
import { parseOptions, vizRegistry } from '../charts/registry'
import { useDisplay } from '../editor/display'
import type { DashboardV2PanelApi } from '../generated/api.schemas'
import type { Panel } from '../spec'
import { DashboardV2PanelMessage } from './DashboardV2PanelMessage'
import { DashboardV2PanelSkeleton } from './DashboardV2PanelSkeleton'
import { useElementSize } from './useElementSize'

export interface DashboardV2PanelChartProps {
    panel: DashboardV2PanelApi
    frames: DataFrame[] | null
    error?: string | null
    range?: { from: number; to: number }
    time?: { from: string; to: string }
    timezone?: string
    onEditPanel?: (edit: (panel: Panel) => Panel) => void
}

export function DashboardV2PanelChart({
    panel,
    frames,
    error,
    range,
    time,
    timezone,
    onEditPanel,
}: DashboardV2PanelChartProps): JSX.Element {
    const [viewed, setViewed] = useState(panel as Panel)
    useEffect(() => setViewed(panel as Panel), [panel])
    const { ref, width, height } = useElementSize<HTMLDivElement>()
    const def = vizRegistry[panel.viz.type]
    const display = useDisplay()
    const parsed = useMemo(
        () => (def ? parseOptions(def, withDisplayDefaults(display, viewed.viz.type, viewed.viz.options)) : null),
        [def, viewed.viz.type, viewed.viz.options, display]
    )
    const drawn = useMemo(
        () =>
            incompleteFrames(
                applyFrameTransforms(
                    frames ?? [],
                    panel.transforms ?? undefined,
                    hiddenRefIds({ targets: panel.targets ?? undefined })
                ),
                incompleteMode(panel)
            ),
        [frames, panel]
    )

    if (!def || !parsed) {
        return (
            <DashboardV2PanelMessage
                title="This chart type isn't available yet"
                detail={`"${panel.viz.type}" charts don't show on this page yet.`}
            />
        )
    }
    if (def.needsData && frames === null) {
        return <DashboardV2PanelSkeleton type={panel.viz.type} />
    }
    const problem = error ?? parsed.error
    if (problem && !drawn.length) {
        return <DashboardV2PanelMessage title="Couldn't load this chart" detail={problem} />
    }
    const Viz = def.component

    return (
        <div ref={ref} className="h-full min-h-0 w-full min-w-0" data-attr="dashboard-v2-panel-chart">
            {width > 0 && height > 0 && (
                <ErrorBoundary key={panel.viz.type} className="h-full overflow-auto">
                    <div className="flex h-full w-full flex-col">
                        <Viz
                            frames={drawn}
                            panel={viewed}
                            onEditPanel={onEditPanel ?? setViewed}
                            options={parsed.options}
                            width={width}
                            height={height}
                            range={range}
                            time={time}
                            timezone={timezone}
                        />
                    </div>
                </ErrorBoundary>
            )}
        </div>
    )
}
