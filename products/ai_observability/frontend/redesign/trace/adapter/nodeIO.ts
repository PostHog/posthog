import type { TraceNodeDetailApi } from '../../../generated/api.schemas'

export interface NodeIO {
    input: unknown
    output: unknown
}

export function readNodeIO(node: TraceNodeDetailApi): NodeIO {
    if (!node.event) {
        return { input: undefined, output: undefined }
    }
    const { properties, ioKeys } = node.event
    return {
        input: ioKeys.input ? properties[ioKeys.input] : undefined,
        output: ioKeys.output ? properties[ioKeys.output] : undefined,
    }
}
