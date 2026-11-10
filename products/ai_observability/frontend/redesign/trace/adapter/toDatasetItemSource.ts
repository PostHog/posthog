import type { SaveToDatasetButtonProps } from '../../../datasets/SaveToDatasetButton'
import type { TraceNodeRawApi } from '../../../generated/api.schemas'
import { RawLoad } from '../types'

interface DatasetItemSourceInput {
    traceId: string
    createdAt: string
    raw: RawLoad | undefined
}

export function toDatasetItemSource({
    traceId,
    createdAt,
    raw,
}: DatasetItemSourceInput): SaveToDatasetButtonProps | null {
    if (raw?.status !== 'ready') {
        return null
    }
    const node = raw.raw
    const { input, output } = readIO(node)
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

function readIO({ event }: Pick<TraceNodeRawApi, 'event'>): { input: unknown; output: unknown } {
    if (!event) {
        return { input: undefined, output: undefined }
    }
    const { properties, ioKeys } = event
    return {
        input: ioKeys.input ? properties[ioKeys.input] : undefined,
        output: ioKeys.output ? properties[ioKeys.output] : undefined,
    }
}

function customProperties(properties: Record<string, unknown>): Record<string, unknown> {
    return Object.fromEntries(Object.entries(properties).filter(([key]) => !key.startsWith('$')))
}
