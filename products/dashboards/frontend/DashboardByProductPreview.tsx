import './DashboardByProductPreview.scss'

type DashboardKind = 'product' | 'web' | 'customer' | 'marketing' | 'ai' | 'mcp' | 'errors'

export function DashboardByProductPreview({ kind }: { kind: DashboardKind }): JSX.Element {
    let content: JSX.Element
    let description: string

    switch (kind) {
        case 'product':
            description = 'Daily active users compared with the previous period.'
            content = (
                <>
                    <text x="8" y="16">
                        Daily active users
                    </text>
                    <path d="M8 100 H272 M8 72 H272 M8 44 H272" stroke="currentColor" opacity="0.12" />
                    <path
                        className="DashboardByProductPreview__area DashboardByProductPreview__area--active-users"
                        d="M8 94 L46 88 L84 80 L122 84 L160 65 L198 57 L236 43 L272 33 L272 108 L8 108 Z"
                        fill="currentColor"
                        opacity="0.1"
                    />
                    <path
                        d="M8 102 L46 98 L84 92 L122 96 L160 84 L198 80 L236 68 L272 62"
                        stroke="currentColor"
                        strokeWidth="2"
                        fill="none"
                        opacity="0.4"
                        strokeDasharray="4 3"
                    />
                    <path
                        className="DashboardByProductPreview__line DashboardByProductPreview__line--active-users"
                        d="M8 94 L46 88 L84 80 L122 84 L160 65 L198 57 L236 43 L272 33"
                        stroke="currentColor"
                        strokeWidth="2"
                        fill="none"
                    />
                    <path d="M8 126 H24" stroke="currentColor" strokeWidth="2" />
                    <text x="30" y="130" className="text-secondary">
                        This period
                    </text>
                    <path d="M140 126 H156" stroke="currentColor" strokeWidth="2" opacity="0.4" strokeDasharray="4 3" />
                    <text x="162" y="130" className="text-secondary">
                        Previous period
                    </text>
                </>
            )
            break
        case 'web':
            description = 'Website visitors compared by traffic channel in a vertical column chart.'
            content = (
                <>
                    <text x="8" y="16">
                        Visitors by channel
                    </text>
                    <path d="M8 110 H272 M8 75 H272 M8 40 H272" stroke="currentColor" opacity="0.12" />
                    {[
                        { label: 'Search', height: 76 },
                        { label: 'Direct', height: 54 },
                        { label: 'Referrals', height: 33 },
                    ].map(({ label, height }, column) => (
                        <g key={label} data-preview-row={column}>
                            <rect
                                className="DashboardByProductPreview__column"
                                x={31 + column * 88}
                                y={110 - height}
                                width="42"
                                height={height}
                                rx="2"
                                fill="currentColor"
                                opacity={0.8 - column * 0.15}
                            />
                            <text x={52 + column * 88} y="132" textAnchor="middle" className="text-secondary">
                                {label}
                            </text>
                        </g>
                    ))}
                </>
            )
            break
        case 'customer':
            description = 'Daily, weekly, and monthly active users over the same period.'
            content = (
                <>
                    <text x="8" y="16">
                        Active users
                    </text>
                    <path d="M8 100 H272 M8 72 H272 M8 44 H272" stroke="currentColor" opacity="0.12" />
                    <path
                        className="DashboardByProductPreview__line DashboardByProductPreview__line--monthly"
                        d="M8 65 L46 58 L84 55 L122 43 L160 38 L198 34 L236 27 L272 23"
                        stroke="currentColor"
                        strokeWidth="2"
                        fill="none"
                        opacity="0.35"
                    />
                    <path
                        className="DashboardByProductPreview__line DashboardByProductPreview__line--weekly"
                        d="M8 82 L46 72 L84 77 L122 60 L160 65 L198 50 L236 55 L272 42"
                        stroke="currentColor"
                        strokeWidth="2"
                        fill="none"
                        opacity="0.65"
                    />
                    <path
                        className="DashboardByProductPreview__line DashboardByProductPreview__line--daily"
                        d="M8 100 L46 85 L84 95 L122 75 L160 91 L198 70 L236 83 L272 62"
                        stroke="currentColor"
                        strokeWidth="2"
                        fill="none"
                    />
                    <circle cx="12" cy="126" r="3" fill="currentColor" />
                    <text x="22" y="130" className="text-secondary">
                        Daily
                    </text>
                    <circle cx="92" cy="126" r="3" fill="currentColor" opacity="0.65" />
                    <text x="102" y="130" className="text-secondary">
                        Weekly
                    </text>
                    <circle cx="190" cy="126" r="3" fill="currentColor" opacity="0.35" />
                    <text x="200" y="130" className="text-secondary">
                        Monthly
                    </text>
                </>
            )
            break
        case 'marketing':
            description = 'Visitors and new customers compared by marketing channel.'
            content = (
                <>
                    <text x="8" y="16">
                        Acquisition by channel
                    </text>
                    {[
                        { label: 'Direct', visitors: 150, customers: 38 },
                        { label: 'Organic search', visitors: 124, customers: 48 },
                        { label: 'Paid search', visitors: 98, customers: 28 },
                    ].map(({ label, visitors, customers }, row) => (
                        <g key={label} data-preview-row={row}>
                            <text x="8" y={48 + row * 28} className="text-secondary">
                                {label}
                            </text>
                            <rect
                                className="DashboardByProductPreview__bar"
                                x="112"
                                y={36 + row * 28}
                                width={visitors}
                                height="16"
                                rx="2"
                                fill="currentColor"
                                opacity="0.25"
                            />
                            <rect
                                className="DashboardByProductPreview__bar"
                                x="112"
                                y={36 + row * 28}
                                width={customers}
                                height="16"
                                rx="2"
                                fill="currentColor"
                                opacity="0.85"
                            />
                        </g>
                    ))}
                    <rect x="8" y="122" width="12" height="8" rx="1" fill="currentColor" opacity="0.25" />
                    <text x="26" y="130" className="text-secondary">
                        Visitors
                    </text>
                    <rect x="128" y="122" width="12" height="8" rx="1" fill="currentColor" opacity="0.85" />
                    <text x="146" y="130" className="text-secondary">
                        New customers
                    </text>
                </>
            )
            break
        case 'ai':
            description = 'Cost and median generation latency compared by model.'
            content = (
                <>
                    <text x="8" y="16">
                        Cost and latency by model
                    </text>
                    <text x="8" y="38" className="text-muted">
                        Model
                    </text>
                    <text x="106" y="38" className="text-muted">
                        Cost
                    </text>
                    <text x="198" y="38" className="text-muted">
                        Latency
                    </text>
                    {[
                        { label: 'Model A', cost: 72, latency: 42 },
                        { label: 'Model B', cost: 56, latency: 64 },
                        { label: 'Model C', cost: 34, latency: 26 },
                    ].map(({ label, cost, latency }, row) => (
                        <g key={label} data-preview-row={row}>
                            <path d={`M8 ${46 + row * 28} H272`} stroke="currentColor" opacity="0.12" />
                            <text x="8" y={64 + row * 28} className="text-secondary">
                                {label}
                            </text>
                            <rect
                                className="DashboardByProductPreview__bar"
                                x="106"
                                y={53 + row * 28}
                                width={cost}
                                height="13"
                                rx="2"
                                fill="currentColor"
                                opacity="0.45"
                            />
                            <rect
                                className="DashboardByProductPreview__bar"
                                x="198"
                                y={53 + row * 28}
                                width={latency}
                                height="13"
                                rx="2"
                                fill="currentColor"
                                opacity="0.8"
                            />
                        </g>
                    ))}
                </>
            )
            break
        case 'mcp':
            description = 'MCP tool calls and errors over the same period.'
            content = (
                <>
                    <text x="8" y="16">
                        Tool calls and errors
                    </text>
                    <path d="M8 100 H272 M8 72 H272 M8 44 H272" stroke="currentColor" opacity="0.12" />
                    <path
                        className="DashboardByProductPreview__line DashboardByProductPreview__line--tool-calls"
                        d="M8 55 L46 65 L84 60 L122 40 L160 30 L198 43 L236 44 L272 38"
                        stroke="currentColor"
                        strokeWidth="2"
                        fill="none"
                    />
                    <path
                        className="DashboardByProductPreview__line DashboardByProductPreview__line--tool-errors"
                        d="M8 103 L46 105 L84 104 L122 100 L160 97 L198 102 L236 101 L272 103"
                        stroke="currentColor"
                        strokeWidth="2"
                        fill="none"
                        opacity="0.5"
                        strokeDasharray="4 3"
                    />
                    <path d="M8 126 H24" stroke="currentColor" strokeWidth="2" />
                    <text x="30" y="130" className="text-secondary">
                        Tool calls
                    </text>
                    <path d="M156 126 H172" stroke="currentColor" strokeWidth="2" opacity="0.5" strokeDasharray="4 3" />
                    <text x="178" y="130" className="text-secondary">
                        Errors
                    </text>
                </>
            )
            break
        case 'errors':
            description = 'Daily exception volume over time.'
            content = (
                <>
                    <text x="8" y="16">
                        Exception volume
                    </text>
                    <path d="M8 110 H272 M8 75 H272 M8 40 H272" stroke="currentColor" opacity="0.12" />
                    {[54, 38, 44, 70, 78, 65, 73].map((height, day) => (
                        <g key={day} data-preview-row={day % 3}>
                            <rect
                                className="DashboardByProductPreview__column"
                                x={18 + day * 36}
                                y={110 - height}
                                width="22"
                                height={height}
                                rx="2"
                                fill="currentColor"
                                opacity="0.8"
                            />
                        </g>
                    ))}
                    <text x="8" y="132" className="text-secondary">
                        Earlier
                    </text>
                    <text x="272" y="132" textAnchor="end" className="text-secondary">
                        Latest
                    </text>
                </>
            )
            break
    }

    return (
        <div className="DashboardByProductPreview bg-surface-secondary px-4 pt-2 pb-3 border-b border-primary">
            <svg
                viewBox="0 0 280 140"
                className="w-full h-36 fill-current text-xs font-medium"
                role="img"
                aria-label={description}
            >
                {content}
            </svg>
        </div>
    )
}
