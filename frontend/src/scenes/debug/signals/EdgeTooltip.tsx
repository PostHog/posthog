import { GraphEdge } from './types'

export function EdgeTooltip({ edge, x, y }: { edge: GraphEdge; x: number; y: number }): JSX.Element {
    return (
        <div
            className="fixed z-50 border rounded-md pointer-events-none text-[13px] bg-surface-primary"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                left: x + 14,
                top: y - 10,
                maxWidth: 360,
                padding: '8px 12px',
                border: '1px solid var(--border)',
                boxShadow: 'var(--shadow-elevation-3000)',
            }}
        >
            <div className="font-semibold mb-1.5 text-[13px]">Match connection</div>
            <div className="text-muted text-xs font-medium mb-0.5">Reason</div>
            <div className="mb-2">{edge.reason}</div>
            <div className="text-muted text-xs font-medium mb-0.5">Query</div>
            <div className="italic">{edge.match_query}</div>
        </div>
    )
}
