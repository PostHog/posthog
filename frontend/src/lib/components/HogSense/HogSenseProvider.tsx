import { type ReactNode, useMemo } from 'react'

import { HogSenseContext } from './HogSenseContext'
import type { Finding, HogSenseRenderMap } from './types'

export function HogSenseProvider({
    findings,
    renderMap,
    children,
}: {
    findings: Finding[]
    renderMap: HogSenseRenderMap
    children: ReactNode
}): JSX.Element {
    const value = useMemo(() => ({ findings, renderMap }), [findings, renderMap])
    return <HogSenseContext.Provider value={value}>{children}</HogSenseContext.Provider>
}
