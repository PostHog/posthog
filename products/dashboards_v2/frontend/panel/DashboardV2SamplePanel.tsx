import { useActions, useValues } from 'kea'
import { createContext, useContext, useMemo, useRef } from 'react'

import { objectsEqual } from 'lib/utils/objects'

import type { DataFrame } from '../charts/frame'
import { applyFrameTransforms, hiddenRefIds, incompleteFrames, incompleteMode } from '../charts/frames'
import { dashboardV2Logic } from '../dashboard/dashboardV2Logic'
import { parseTimeExpression } from '../dashboard/timeRange'
import { panelEditorLogic } from '../editor/panelEditorLogic'
import type { DashboardV2PanelApi } from '../generated/api.schemas'
import { DashboardV2Panel } from './DashboardV2Panel'
import type { DashboardV2PanelChartProps } from './DashboardV2PanelChart'
import { sampleFrames } from './sampleFrames'

const SIX_HOURS_MS = 21_600_000

export const DashboardV2EditablePanelsContext = createContext(false)

function useSampleRange(): { from: number; to: number } {
    const { timeRange } = useValues(dashboardV2Logic)
    const { from, to } = timeRange

    return useMemo(() => {
        const now = new Date()
        const end = parseTimeExpression(to, now, true)?.getTime() ?? now.getTime()
        const start = parseTimeExpression(from, now)?.getTime() ?? end - SIX_HOURS_MS
        return { from: start, to: end }
    }, [from, to])
}

export function useSampleFrames(id: string, panel: DashboardV2PanelApi): DataFrame[] {
    const range = useSampleRange()

    return useMemo(
        () =>
            incompleteFrames(
                applyFrameTransforms(
                    sampleFrames(id, panel, range),
                    panel.transforms ?? undefined,
                    hiddenRefIds({ targets: panel.targets ?? undefined })
                ),
                incompleteMode(panel)
            ),
        [id, panel, range]
    )
}

interface DashboardV2SamplePanelProps {
    id: string
    panel: DashboardV2PanelApi
    onEditPanel?: DashboardV2PanelChartProps['onEditPanel']
}

export function DashboardV2SamplePanel({ id, panel, onEditPanel }: DashboardV2SamplePanelProps): JSX.Element {
    const { timeRange, spec } = useValues(dashboardV2Logic)
    const { openPanelId, draft } = useValues(panelEditorLogic)
    const { openPanel, duplicatePanel, confirmRemovePanel } = useActions(panelEditorLogic)
    const editable = useContext(DashboardV2EditablePanelsContext)
    const range = useSampleRange()

    const kept = useRef(panel)
    if (kept.current !== panel && !objectsEqual(kept.current, panel)) {
        kept.current = panel
    }
    const shown = editable && openPanelId === id && draft ? draft : kept.current
    const frames = useMemo(() => sampleFrames(id, shown, range), [id, shown, range])

    return (
        <DashboardV2Panel
            id={editable ? id : undefined}
            panel={shown}
            frames={frames}
            sample
            range={range}
            time={timeRange}
            timezone={spec?.timezone ?? undefined}
            onEditPanel={onEditPanel}
            onView={editable ? () => openPanel(id, 'view') : undefined}
            onEdit={editable ? () => openPanel(id, 'edit') : undefined}
            onDuplicate={editable ? () => duplicatePanel(id) : undefined}
            onRemove={editable ? () => confirmRemovePanel(id) : undefined}
        />
    )
}
