import type { CompatMessage } from '../../../../types'
import type { Scope } from '../../scope'
import type { EmitSpec } from '../../spec/emitSpec'

// Distinguishes "no rule matched" (keep scanning) from "a rule matched and
// produced zero messages" (a committed empty result).
export const NO_MATCH = Symbol('no-match')
export type DispatchResult = CompatMessage[] | typeof NO_MATCH

// The ast layer declares this contract so it never imports from runtime/;
// SlotCoercer is the implementation.
export interface MessageBuilder {
    buildMessage(emit: EmitSpec, scope: Scope, allowDrop?: boolean): CompatMessage | null
    stamp(message: CompatMessage, emit: EmitSpec, scope: Scope): CompatMessage
}

export interface DispatchEngine {
    dispatch(input: unknown, inheritedRole: string, depth: number): DispatchResult
    readonly coercer: MessageBuilder
}
