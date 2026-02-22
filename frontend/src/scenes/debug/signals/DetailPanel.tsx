import { useCallback, useRef, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { sourceProductColor } from './helpers'
import { SignalNode, isMatchedMetadata } from './types'

function Section({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div>
            <div className="text-muted text-xs font-semibold uppercase tracking-wide mb-1">{label}</div>
            <div>{children}</div>
        </div>
    )
}

export function DetailPanel({
    signal,
    isRoot,
    onClose,
}: {
    signal: SignalNode
    isRoot: boolean
    onClose: () => void
}): JSX.Element {
    const panelRef = useRef<HTMLDivElement>(null)
    const [size, setSize] = useState({ width: 420, height: 500 })
    const [position, setPosition] = useState({ x: 16, y: 16 })
    const dragState = useRef<{ startX: number; startY: number; startPosX: number; startPosY: number } | null>(null)
    const resizeState = useRef<{ startX: number; startY: number; startW: number; startH: number } | null>(null)

    // Drag handler
    const onDragMouseDown = useCallback(
        (e: React.MouseEvent) => {
            // Don't start drag if clicking a button
            if ((e.target as HTMLElement).closest('button')) {
                return
            }
            e.preventDefault()
            dragState.current = { startX: e.clientX, startY: e.clientY, startPosX: position.x, startPosY: position.y }
            const onMove = (ev: MouseEvent): void => {
                if (!dragState.current) {
                    return
                }
                const dx = ev.clientX - dragState.current.startX
                const dy = ev.clientY - dragState.current.startY
                setPosition({ x: dragState.current.startPosX - dx, y: dragState.current.startPosY + dy })
            }
            const onUp = (): void => {
                dragState.current = null
                document.removeEventListener('mousemove', onMove)
                document.removeEventListener('mouseup', onUp)
            }
            document.addEventListener('mousemove', onMove)
            document.addEventListener('mouseup', onUp)
        },
        [position]
    )

    // Resize handler (drag from left edge)
    const onResizeMouseDown = useCallback(
        (e: React.MouseEvent) => {
            e.preventDefault()
            e.stopPropagation()
            resizeState.current = { startX: e.clientX, startY: e.clientY, startW: size.width, startH: size.height }
            const onMove = (ev: MouseEvent): void => {
                if (!resizeState.current) {
                    return
                }
                const dx = resizeState.current.startX - ev.clientX
                const dy = ev.clientY - resizeState.current.startY
                setSize({
                    width: Math.max(320, resizeState.current.startW + dx),
                    height: Math.max(300, resizeState.current.startH + dy),
                })
            }
            const onUp = (): void => {
                resizeState.current = null
                document.removeEventListener('mousemove', onMove)
                document.removeEventListener('mouseup', onUp)
            }
            document.addEventListener('mousemove', onMove)
            document.addEventListener('mouseup', onUp)
        },
        [size]
    )

    return (
        <div
            ref={panelRef}
            className="absolute flex flex-col z-20 overflow-hidden rounded-md bg-surface-primary"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: size.width,
                height: size.height,
                right: position.x,
                top: position.y,
                border: '1px solid var(--border)',
                boxShadow: 'var(--shadow-elevation-3000)',
            }}
        >
            {/* Resize handle — left edge */}
            <div
                className="absolute left-0 top-0 bottom-0 cursor-ew-resize z-30 hover:bg-primary/10 transition-colors"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: 5 }}
                onMouseDown={onResizeMouseDown}
            />
            {/* Resize handle — bottom edge */}
            <div
                className="absolute left-0 right-0 bottom-0 cursor-ns-resize z-30 hover:bg-primary/10 transition-colors"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ height: 5 }}
                onMouseDown={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    const startY = e.clientY
                    const startH = size.height
                    const onMove = (ev: MouseEvent): void => {
                        setSize((s) => ({ ...s, height: Math.max(300, startH + (ev.clientY - startY)) }))
                    }
                    const onUp = (): void => {
                        document.removeEventListener('mousemove', onMove)
                        document.removeEventListener('mouseup', onUp)
                    }
                    document.addEventListener('mousemove', onMove)
                    document.addEventListener('mouseup', onUp)
                }}
            />
            {/* Drag handle — title bar */}
            <div
                className="flex items-center justify-between px-3 py-2 border-b cursor-grab active:cursor-grabbing select-none shrink-0"
                onMouseDown={onDragMouseDown}
            >
                <span className="font-semibold text-[13px]">Signal details</span>
                <LemonButton size="small" onClick={onClose}>
                    ✕
                </LemonButton>
            </div>
            <div className="p-4 space-y-4 text-[13px] overflow-y-auto flex-1">
                <Section label="Signal ID">
                    <code className="text-xs break-all select-all">{signal.signal_id}</code>
                </Section>
                <Section label="Source">
                    <div className="flex items-center gap-1.5">
                        <span
                            className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ backgroundColor: sourceProductColor(signal.source_product) }}
                        />
                        <span>
                            {signal.source_product} / {signal.source_type}
                        </span>
                    </div>
                </Section>
                <div className="flex gap-6">
                    <Section label="Weight">{signal.weight}</Section>
                    <Section label="Timestamp">{signal.timestamp}</Section>
                </div>
                {isRoot && (
                    <div className="text-xs font-medium text-primary bg-primary-highlight rounded px-2 py-1 inline-block">
                        Root signal (started this group)
                    </div>
                )}
                <Section label="Description">
                    <div className="whitespace-pre-wrap text-[13px] leading-relaxed rounded p-2.5 border bg-surface-secondary">
                        {signal.content}
                    </div>
                </Section>
                {signal.source_id && (
                    <Section label="Source ID">
                        <code className="text-xs select-all">{signal.source_id}</code>
                    </Section>
                )}
                {signal.extra && Object.keys(signal.extra).length > 0 && (
                    <Section label="Extra metadata">
                        <pre className="text-xs whitespace-pre-wrap rounded p-2.5 border overflow-x-auto bg-surface-secondary">
                            {JSON.stringify(signal.extra, null, 2)}
                        </pre>
                    </Section>
                )}
                {signal.match_metadata && (
                    <Section label="Match metadata">
                        {isMatchedMetadata(signal.match_metadata) ? (
                            <div className="space-y-3 rounded border p-2.5 bg-surface-secondary">
                                <div>
                                    <span className="text-muted text-xs font-medium">Matched to parent</span>
                                    <code className="block text-xs break-all select-all mt-0.5">
                                        {signal.match_metadata.parent_signal_id}
                                    </code>
                                </div>
                                <div className="text-muted text-xs italic">
                                    Hover the arrow to see the match query and reason
                                </div>
                            </div>
                        ) : (
                            <div className="space-y-3 rounded border p-2.5 bg-surface-secondary">
                                <div>
                                    <span className="text-muted text-xs font-medium">Reason (no match)</span>
                                    <div className="text-[13px] mt-0.5">{signal.match_metadata.reason}</div>
                                </div>
                                {signal.match_metadata.rejected_signal_ids.length > 0 && (
                                    <div>
                                        <span className="text-muted text-xs font-medium">
                                            Rejected signals ({signal.match_metadata.rejected_signal_ids.length})
                                        </span>
                                        <div className="mt-0.5 space-y-0.5">
                                            {signal.match_metadata.rejected_signal_ids.map((id) => (
                                                <code key={id} className="block text-xs break-all select-all">
                                                    {id}
                                                </code>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}
                    </Section>
                )}
            </div>
        </div>
    )
}
