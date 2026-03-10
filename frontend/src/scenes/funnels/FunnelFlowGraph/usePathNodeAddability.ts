import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelPathType } from '~/types'

import { funnelFlowGraphLogic } from './funnelFlowGraphLogic'

export function usePathNodeAddability(): boolean {
    const { insightProps } = useValues(insightLogic)
    const { expandedPath, funnelNodes } = useValues(funnelFlowGraphLogic({ ...insightProps, isProfileMode: false }))

    if (!expandedPath) {
        return false
    }

    const { pathType, dropOff, stepIndex } = expandedPath
    if (dropOff) {
        return false
    }

    const lastIndex = funnelNodes.length - 1

    if (pathType === FunnelPathType.between) {
        return true
    }
    if (pathType === FunnelPathType.before) {
        return stepIndex === 0
    }
    if (pathType === FunnelPathType.after) {
        return stepIndex === lastIndex
    }

    return false
}
