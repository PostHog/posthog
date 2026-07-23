import posthog from 'posthog-js'

import { CompatMessage } from '../../../types'
import { LiteralExpr } from '../ast/expr'
import { Scope } from '../scope'
import { EmitSpec } from '../spec/emitSpec'
import { SlotCoercer } from './coercion'

jest.mock('posthog-js', () => ({ __esModule: true, default: { capture: jest.fn() } }))

const coercer = new SlotCoercer()
const scope = (input: unknown = {}, role = 'user'): Scope => Scope.forNode(input, role)
const lit = (value: unknown): LiteralExpr => new LiteralExpr(value)

describe('SlotCoercer.buildMessage', () => {
    beforeEach(() => jest.clearAllMocks())

    it('builds a message with role and content', () => {
        const emit: EmitSpec = { content: lit('hello') }
        expect(coercer.buildMessage(emit, scope({}, 'assistant'))).toEqual({ role: 'assistant', content: 'hello' })
    })

    it('maps a role tag to the renderer-facing role string', () => {
        const emit: EmitSpec = { role: 'tool_result', content: lit('done') }
        expect(coercer.buildMessage(emit, scope())).toEqual({ role: 'assistant (tool result)', content: 'done' })
    })

    it('normalizes a function-shaped tool call into the canonical form', () => {
        const emit: EmitSpec = {
            toolCall: lit({
                type: 'function',
                id: 'c1',
                function: { name: 'get_weather', arguments: { city: 'NYC' } },
            }),
        }
        expect(coercer.buildMessage(emit, scope())?.tool_calls).toEqual([
            { type: 'function', id: 'c1', function: { name: 'get_weather', arguments: { city: 'NYC' } } },
        ])
    })

    it('normalizes a bare {name, args} tool call', () => {
        const emit: EmitSpec = { toolCall: lit({ id: 'c2', name: 'search', args: { q: 'hog' } }) }
        expect(coercer.buildMessage(emit, scope())?.tool_calls).toEqual([
            { type: 'function', id: 'c2', function: { name: 'search', arguments: { q: 'hog' } } },
        ])
    })

    it('parses string tool-call arguments into an object', () => {
        const emit: EmitSpec = { toolCall: lit({ name: 'search', arguments: '{"q":"hog"}' }) }
        expect(coercer.buildMessage(emit, scope())?.tool_calls?.[0].function.arguments).toEqual({ q: 'hog' })
    })

    it('keeps unparseable string arguments as a raw string', () => {
        const emit: EmitSpec = { toolCall: lit({ name: 'search', arguments: '{not json' }) }
        expect(coercer.buildMessage(emit, scope())?.tool_calls?.[0].function.arguments).toBe('{not json')
    })

    it('collapses a single-item text array to a plain string', () => {
        const emit: EmitSpec = { content: lit(['only one']) }
        expect(coercer.buildMessage(emit, scope())?.content).toBe('only one')
    })

    it('defaults missing content to an empty string', () => {
        const emit: EmitSpec = { role: 'user' }
        expect(coercer.buildMessage(emit, scope())).toEqual({ role: 'user', content: '' })
    })

    it('spread fills the base while explicit slots win', () => {
        const emit: EmitSpec = {
            spread: lit({ content: 'from spread', extra: 1 }),
            role: 'system',
            content: lit('override'),
        }
        expect(coercer.buildMessage(emit, scope())).toEqual({ role: 'system', content: 'override', extra: 1 })
    })

    it('drops to null when the message is empty and dropping is allowed', () => {
        const emit: EmitSpec = { role: 'user' }
        expect(coercer.buildMessage(emit, scope(), true)).toBeNull()
    })

    it('non-text content yields an empty string instead of leaking JSON', () => {
        const emit: EmitSpec = { content: lit({ unexpected: 'object' }) }
        expect(coercer.buildMessage(emit, scope())?.content).toBe('')
        expect(posthog.capture).toHaveBeenCalled()
    })
})

describe('SlotCoercer.stamp', () => {
    it('overrides role and tool_call_id on an already-built message', () => {
        const message: CompatMessage = { role: 'user', content: 'r' }
        const emit: EmitSpec = { role: 'tool_result', toolCallId: lit('tc1') }
        expect(coercer.stamp(message, emit, scope())).toEqual({
            role: 'assistant (tool result)',
            content: 'r',
            tool_call_id: 'tc1',
        })
    })

    it('leaves fields untouched when emit slots are absent', () => {
        const message: CompatMessage = { role: 'assistant', content: 'r' }
        expect(coercer.stamp(message, {}, scope())).toEqual({ role: 'assistant', content: 'r' })
    })
})
