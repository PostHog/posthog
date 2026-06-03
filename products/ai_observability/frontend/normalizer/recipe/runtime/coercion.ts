import posthog from 'posthog-js'

import { CompatMessage, CompatToolCall, MultiModalContentItem } from '../../../types'
import { normalizeRole } from '../../../utils'
import { Expr } from '../ast/expr'
import { Scope } from '../scope'
import { EmitSpec, RoleTag } from '../spec/emitSpec'

// Maps symbolic role tags to the legacy renderer-facing strings; a temporary
// shim until the renderer can consume the symbolic tags directly.
const ROLE_TAGS: Record<RoleTag, string> = {
    user: 'user',
    assistant: 'assistant',
    system: 'system',
    tool: 'tool',
    thinking: 'assistant (thinking)',
    tool_result: 'assistant (tool result)',
}

export class SlotCoercer {
    buildMessage(emit: EmitSpec, scope: Scope, allowDrop: boolean = false): CompatMessage | null {
        // Spread first, so the explicit slots below override it.
        let base: Partial<CompatMessage> = {}
        if (emit.spread !== undefined) {
            const spread = emit.spread.eval(scope)
            if (spread && typeof spread === 'object' && !Array.isArray(spread)) {
                base = { ...(spread as Record<string, unknown>) } as Partial<CompatMessage>
            }
        }

        const role = this.coerceRole(emit.role, scope)

        if (emit.content !== undefined) {
            base.content = this.coerceContent(emit.content.eval(scope))
        }
        if (emit.toolCallId !== undefined) {
            const id = emit.toolCallId.eval(scope)
            if (typeof id === 'string') {
                base.tool_call_id = id
            }
        }
        if (emit.toolCall !== undefined) {
            const normalized = this.coerceSingleToolCall(emit.toolCall.eval(scope))
            if (normalized) {
                base.tool_calls = [normalized]
            }
        }
        if (emit.toolCalls !== undefined) {
            // Explicit override: assigning `undefined` clears any value the
            // spread may have put there.
            base.tool_calls = this.coerceToolCalls(emit.toolCalls.eval(scope))
        }

        const isEmpty =
            base.content === undefined &&
            base.tool_calls === undefined &&
            base.tool_call_id === undefined &&
            (base as { tools?: unknown }).tools === undefined

        if (allowDrop && isEmpty) {
            return null
        }
        // Renderers expect a string, so default empty content rather than leave it undefined.
        return { ...base, role, content: base.content ?? '' }
    }

    // Attaches the parent's role/tool_call_id onto children that normalized
    // independently via `delegateEach` (the Anthropic tool_result case).
    stamp(message: CompatMessage, emit: EmitSpec, scope: Scope): CompatMessage {
        const stamped: CompatMessage = { ...message }
        if (emit.role !== undefined) {
            stamped.role = this.coerceRole(emit.role, scope)
        }
        if (emit.toolCallId !== undefined) {
            const id = emit.toolCallId.eval(scope)
            if (typeof id === 'string') {
                stamped.tool_call_id = id
            }
        }
        return stamped
    }

    private coerceRole(roleExpr: Expr | RoleTag | undefined, scope: Scope): string {
        const defaultRole = scope.role
        if (roleExpr === undefined) {
            return defaultRole
        }
        if (typeof roleExpr === 'string') {
            return normalizeRole(ROLE_TAGS[roleExpr], defaultRole)
        }
        const evaluated = roleExpr.eval(scope)
        if (typeof evaluated === 'string') {
            return normalizeRole(evaluated, defaultRole)
        }
        return defaultRole
    }

    private coerceContent(value: unknown): CompatMessage['content'] | undefined {
        if (value === undefined) {
            return undefined
        }
        if (value === null) {
            return ''
        }
        if (typeof value === 'string') {
            return value
        }
        if (Array.isArray(value)) {
            // Empties are not dropped here — recipes opt into that with `if_empty: ~`.
            if (value.length > 0 && value.every((v) => typeof v === 'string')) {
                if (value.length === 1) {
                    return value[0]
                }
                return value.map((text) => ({ type: 'text' as const, text: text as string }))
            }
            return value as MultiModalContentItem[]
        }
        // Reaching here is a recipe bug or coverage gap (recipes opt into rendering
        // arbitrary values with `stringify`); surface '' rather than plausible-looking
        // JSON, and log type only since the value may be sensitive.
        posthog.capture('llma recipe produced non-text content', { content_type: typeof value })
        return ''
    }

    private coerceToolCalls(value: unknown): CompatToolCall[] | undefined {
        if (!Array.isArray(value) || value.length === 0) {
            return undefined
        }
        const calls: CompatToolCall[] = []
        for (const item of value) {
            const normalized = this.coerceSingleToolCall(item)
            if (normalized) {
                calls.push(normalized)
            }
        }
        return calls.length > 0 ? calls : undefined
    }

    private coerceSingleToolCall(value: unknown): CompatToolCall | null {
        if (!value || typeof value !== 'object') {
            return null
        }
        const obj = value as Record<string, unknown>
        if (obj.type === 'function' && obj.function && typeof obj.function === 'object') {
            const fn = obj.function as { name: unknown; arguments?: unknown }
            if (typeof fn.name !== 'string') {
                return null
            }
            return {
                type: 'function',
                id: typeof obj.id === 'string' ? obj.id : undefined,
                function: {
                    name: fn.name,
                    arguments: parseToolArguments(fn.arguments ?? {}),
                },
            }
        }
        if (typeof obj.name === 'string') {
            const argsRaw = obj.args ?? obj.arguments ?? {}
            return {
                type: 'function',
                id: typeof obj.id === 'string' ? obj.id : undefined,
                function: {
                    name: obj.name,
                    arguments:
                        typeof argsRaw === 'string'
                            ? parseToolArguments(argsRaw)
                            : (argsRaw as Record<string, unknown>),
                },
            }
        }
        return null
    }
}

function parseToolArguments(args: string | Record<string, unknown> | unknown): Record<string, unknown> | string {
    if (typeof args === 'string') {
        try {
            return JSON.parse(args)
        } catch {
            return args
        }
    }
    if (args && typeof args === 'object') {
        return args as Record<string, unknown>
    }
    return {}
}
