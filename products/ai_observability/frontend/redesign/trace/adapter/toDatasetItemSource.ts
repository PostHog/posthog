import type { SaveToDatasetButtonProps } from '../../../datasets/SaveToDatasetButton'
import { NodeLoad } from '../types'
import { readNodeIO } from './nodeIO'

interface DatasetItemSourceInput {
    traceId: string
    createdAt: string
    load: NodeLoad
}

export function toDatasetItemSource({
    traceId,
    createdAt,
    load,
}: DatasetItemSourceInput): SaveToDatasetButtonProps | null {
    if (load.status !== 'ready') {
        return null
    }
    const { node } = load
    const { input, output } = readNodeIO(node)
    if (node.kind === 'trace') {
        return { traceId, timestamp: createdAt, sourceId: traceId, input, output }
    }
    if (!node.event) {
        return null
    }
    return {
        traceId,
        timestamp: createdAt,
        sourceId: node.event.uuid,
        input,
        output,
        metadata: customProperties(node.event.properties),
    }
}

function customProperties(properties: Record<string, unknown>): Record<string, unknown> {
    return Object.fromEntries(Object.entries(properties).filter(([key]) => !key.startsWith('$')))
}
