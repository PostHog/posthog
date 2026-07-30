/**
 * id→class accessor for native-tool approval, injected into the approval
 * resolver in agent-shared (which can't import the registry without a cycle).
 * The class is declared at each tool's definition site; a spec may tighten an
 * individual ref but never loosen below it.
 */
import type { NativeApprovalClass } from '@posthog/agent-shared'

import { getNativeTool, hasNativeTool } from './registry'

export type { NativeApprovalClass }

/** Unregistered native id ⇒ gated. Fail closed. */
export const FAIL_CLOSED_NATIVE_APPROVAL: NativeApprovalClass = 'approve'

/** Intrinsic approval class for a native tool id, read from its definition.
 *  Fail closed on an id no registered tool declares. */
export function nativeToolApprovalClass(id: string): NativeApprovalClass {
    return hasNativeTool(id) ? getNativeTool(id).schema.approval : FAIL_CLOSED_NATIVE_APPROVAL
}
