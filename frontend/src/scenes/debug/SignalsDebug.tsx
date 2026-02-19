import { useCallback, useMemo, useState } from 'react'

import api from 'lib/api'
import { useLocalStorage } from 'lib/hooks/useLocalStorage'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { DetailPanel } from './signals/DetailPanel'
import { EdgeTooltip } from './signals/EdgeTooltip'
import { ReportListPanel } from './signals/ReportListPanel'
import { SignalGraph } from './signals/SignalGraph'
import { SimulationControls } from './signals/SimulationControls'
import { statusBadgeColor } from './signals/helpers'
import type { GraphEdge, ReportData, ReportSignalsResponse, SignalNode, SimConfig } from './signals/types'
import { DEFAULT_CONFIG } from './signals/types'
import { useD3ForceSimulation } from './signals/useD3ForceSimulation'

export function SignalsDebug(): JSX.Element {
    const [reportId, setReportId] = useState('')
    const [loading, setLoading] = useState(false)
    const [report, setReport] = useState<ReportData | null>(null)
    const [signals, setSignals] = useState<SignalNode[]>([])
    const [loaded, setLoaded] = useState(false)
    const [selectedSignalId, setSelectedSignalId] = useState<string | null>(null)
    const [hoveredEdge, setHoveredEdge] = useState<GraphEdge | null>(null)
    const [mousePos, setMousePos] = useState({ x: 0, y: 0 })
    const [simConfig, setSimConfig] = useLocalStorage<SimConfig>('signals-debug-physics', { ...DEFAULT_CONFIG })

    const {
        positions,
        edges,
        containerRef,
        onNodeDragStart,
        draggedNodeId,
        didDragRef,
        transform,
        viewportCenter,
        resetView,
    } = useD3ForceSimulation(signals, simConfig)

    const rootIds = useMemo(() => {
        const childIds = new Set(edges.map((e) => e.target))
        return new Set(signals.filter((s) => !childIds.has(s.signal_id)).map((s) => s.signal_id))
    }, [signals, edges])

    const selectedSignal = useMemo(
        () => (selectedSignalId ? (signals.find((s) => s.signal_id === selectedSignalId) ?? null) : null),
        [signals, selectedSignalId]
    )

    const loadReport = useCallback(async (id: string) => {
        const trimmed = id.trim()
        if (!trimmed) {
            return
        }
        // Clear everything immediately to prevent artefacting from the previous report
        setSignals([])
        setReport(null)
        setSelectedSignalId(null)
        setHoveredEdge(null)
        setLoaded(false)
        setLoading(true)
        try {
            const response = await api.get<ReportSignalsResponse>(
                `api/environments/@current/signals/report_signals/?report_id=${encodeURIComponent(trimmed)}`
            )
            setReport(response.report)
            setSignals(response.signals)
            setLoaded(true)
            if (response.signals.length === 0) {
                lemonToast.info('No signals found for this report')
            }
        } catch (error) {
            lemonToast.error(`Failed to load signals: ${error}`)
        } finally {
            setLoading(false)
        }
    }, [])

    const handleLoad = useCallback(() => {
        void loadReport(reportId)
    }, [reportId, loadReport])

    const handleSelectReport = useCallback(
        (id: string) => {
            setReportId(id)
            void loadReport(id)
        },
        [loadReport]
    )

    const handleKeyDown = useCallback(
        (e: React.KeyboardEvent) => {
            if (e.key === 'Enter') {
                void handleLoad()
            }
        },
        [handleLoad]
    )

    const handleMouseMove = useCallback((e: React.MouseEvent) => {
        setMousePos({ x: e.clientX, y: e.clientY })
    }, [])

    return (
        <SceneContent className="h-full flex flex-col grow gap-y-1">
            {/* Header */}
            <div className="shrink-0 flex items-baseline gap-3 pb-1 border-b">
                <h1 className="text-xl font-bold shrink-0">Signal report explorer</h1>
                <div className="flex gap-2 items-center flex-1" style={{ maxWidth: '33%' }}>
                    <LemonInput
                        fullWidth
                        size="small"
                        value={reportId}
                        onChange={setReportId}
                        onKeyDown={handleKeyDown}
                        placeholder="Enter report UUID..."
                        className="font-mono"
                    />
                    <LemonButton
                        size="small"
                        type="primary"
                        onClick={handleLoad}
                        loading={loading}
                        disabled={!reportId.trim()}
                    >
                        Load
                    </LemonButton>
                </div>
            </div>

            {/* Main area — report list on left, graph on right */}
            <div className="relative grow flex overflow-hidden">
                {/* Report list panel */}
                <ReportListPanel selectedReportId={report?.id ?? null} onSelectReport={handleSelectReport} />

                {/* Graph area */}
                <div className="relative grow border rounded bg-surface-primary overflow-hidden">
                    {/* Report summary overlay */}
                    {report && (
                        <div
                            className="absolute top-3 left-3 z-20 flex items-center gap-2 rounded-md bg-surface-primary/80 backdrop-blur text-sm select-none pointer-events-none"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                border: '1px solid var(--border)',
                                padding: '4px 10px',
                                maxWidth: 'calc(100% - 24px)',
                            }}
                        >
                            <span
                                className={`text-[10px] font-medium rounded px-1.5 py-0.5 shrink-0 ${statusBadgeColor(report.status)}`}
                            >
                                {report.status}
                            </span>
                            {report.title && <span className="font-medium truncate text-xs">{report.title}</span>}
                            <span className="text-muted text-[11px] shrink-0">
                                {signals.length} signal{signals.length !== 1 ? 's' : ''} · w
                                {report.total_weight.toFixed(2)}
                            </span>
                        </div>
                    )}
                    {loading && (
                        <div className="absolute inset-0 flex items-center justify-center z-30">
                            <Spinner />
                        </div>
                    )}
                    {!loaded && !loading && (
                        <div className="flex items-center justify-center h-full text-muted text-sm">
                            Select a report from the list or enter a UUID above
                        </div>
                    )}
                    {loaded && signals.length === 0 && !loading && (
                        <div className="flex items-center justify-center h-full text-muted text-sm">
                            No signals found for this report
                        </div>
                    )}
                    {loaded && signals.length > 0 && (
                        <SignalGraph
                            signals={signals}
                            positions={positions}
                            edges={edges}
                            selectedSignalId={selectedSignalId}
                            onSelectSignal={setSelectedSignalId}
                            hoveredEdge={hoveredEdge}
                            onHoverEdge={setHoveredEdge}
                            onMouseMove={handleMouseMove}
                            containerRef={containerRef}
                            onNodeDragStart={onNodeDragStart}
                            draggedNodeId={draggedNodeId}
                            didDragRef={didDragRef}
                            transform={transform}
                        />
                    )}
                    {/* Detail panel */}
                    {selectedSignal && (
                        <DetailPanel
                            signal={selectedSignal}
                            isRoot={rootIds.has(selectedSignal.signal_id)}
                            onClose={() => setSelectedSignalId(null)}
                        />
                    )}
                    {/* Edge hover tooltip */}
                    {hoveredEdge && <EdgeTooltip edge={hoveredEdge} x={mousePos.x} y={mousePos.y} />}
                    {/* Zoom level & viewport center indicator */}
                    {loaded && signals.length > 0 && (
                        <div
                            className="absolute bottom-3 left-3 z-20 flex items-center gap-1.5 rounded-md bg-surface-primary text-xs text-muted font-mono tabular-nums select-none"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                border: '1px solid var(--border)',
                                padding: '4px 8px',
                            }}
                        >
                            <span>{Math.round(transform.k * 100)}%</span>
                            <span className="opacity-40">·</span>
                            <span>
                                {viewportCenter.x}, {viewportCenter.y}
                            </span>
                            <LemonButton size="xsmall" type="tertiary" onClick={resetView} className="ml-1">
                                Reset
                            </LemonButton>
                        </div>
                    )}
                    {/* Physics tuning panel */}
                    {loaded && signals.length > 0 && <SimulationControls config={simConfig} onChange={setSimConfig} />}
                </div>
            </div>
        </SceneContent>
    )
}

export default SignalsDebug
