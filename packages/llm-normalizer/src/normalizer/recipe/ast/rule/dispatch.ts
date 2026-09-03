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

// Charged as work happens so a runaway recipe trips a ceiling instead of the process;
// ExecutionBudget is the implementation.
export interface WorkBudget {
    chargeOperations(count: number): void
    chargeMessages(count: number): void
}

export interface DispatchEngine {
    dispatch(input: unknown, inheritedRole: string, depth: number): DispatchResult
    readonly coercer: MessageBuilder
    readonly budget: WorkBudget
}
