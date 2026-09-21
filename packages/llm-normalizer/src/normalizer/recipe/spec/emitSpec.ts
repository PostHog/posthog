// Inert specs (not self-evaluating AST nodes): `SlotCoercer` interprets `EmitSpec`
// and `Rule.buildFollowups` interprets `FollowupSpec`.

import type { Expr } from '../ast/expr'

export interface EmitSpec {
    role?: Expr | RoleTag
    content?: Expr
    toolCall?: Expr
    toolCalls?: Expr
    toolCallId?: Expr
    spread?: Expr
}

// Extra messages produced after the primary: a static one, or one per element
// of a runtime array (`expand`).
export type FollowupSpec = { kind: 'static'; emit: EmitSpec } | { kind: 'expand'; from: Expr; each: EmitSpec }

export type RoleTag = 'user' | 'assistant' | 'system' | 'tool' | 'thinking' | 'tool_result'
