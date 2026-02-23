import type { Finding } from './types'

interface HogSenseRendererProps {
    findings: Finding[]
    slot?: string
    children: (findings: Finding[]) => React.ReactNode
}

export function HogSenseRenderer({ findings, slot, children }: HogSenseRendererProps): React.ReactNode {
    const filtered = slot ? findings.filter((f) => f.slot === slot) : findings
    if (filtered.length === 0) {
        return null
    }
    return children(filtered)
}
