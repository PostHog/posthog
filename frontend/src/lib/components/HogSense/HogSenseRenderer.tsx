import type { Finding } from './types'

interface HogSenseRendererProps {
    findings: Finding[]
    ids?: readonly string[]
    children: (findings: Finding[]) => React.ReactNode
}

export function HogSenseRenderer({ findings, ids, children }: HogSenseRendererProps): React.ReactNode {
    const filtered = ids ? findings.filter((f) => ids.includes(f.id)) : findings
    if (filtered.length === 0) {
        return null
    }
    return children(filtered)
}
