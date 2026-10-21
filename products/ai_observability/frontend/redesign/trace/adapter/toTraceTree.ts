import { LLMTraceEvent } from '~/queries/schema/schema-general'

import type { TraceNodeApi } from '../../../generated/api.schemas'
import { toDisplayText } from '../components/jsonText'

export function isErrorEvent(event: LLMTraceEvent): boolean {
    const isErrorFlag = event.properties.$ai_is_error
    return !!event.properties.$ai_error || isErrorFlag === true || isErrorFlag === 'true'
}

export function eventError(event: LLMTraceEvent): string | null {
    return isErrorEvent(event) ? toDisplayText(event.properties.$ai_error ?? 'This step failed.') : null
}

export function findTreeNode(nodes: TraceNodeApi[], id: string): TraceNodeApi | null {
    for (const node of nodes) {
        if (node.id === id) {
            return node
        }
        const found = findTreeNode(node.children, id)
        if (found) {
            return found
        }
    }
    return null
}
