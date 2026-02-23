import { createContext } from 'react'

import type { Finding, HogSenseRenderMap } from './types'

export interface HogSenseContextValue {
    findings: Finding[]
    renderMap: HogSenseRenderMap
}

export const HogSenseContext = createContext<HogSenseContextValue | null>(null)
