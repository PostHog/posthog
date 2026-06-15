import { describe, expect, it } from 'vitest'

import { defaultMaxOutputTokensForReasoning, resolveMaxOutputTokens } from './max-output-tokens'

describe('max-output-tokens', () => {
    describe('defaultMaxOutputTokensForReasoning', () => {
        it.each([
            [undefined, 4096],
            ['minimal' as const, 4096],
            ['low' as const, 8192],
            ['medium' as const, 16384],
            ['high' as const, 24576],
            ['xhigh' as const, 24576],
        ])('reasoning=%s → %d', (reasoning, expected) => {
            expect(defaultMaxOutputTokensForReasoning(reasoning)).toBe(expected)
        })
    })

    describe('resolveMaxOutputTokens', () => {
        it('uses the reasoning-aware default when spec is unset', () => {
            const out = resolveMaxOutputTokens({
                modelMaxTokens: 32_000,
                configOverride: undefined,
                specRequested: undefined,
                reasoning: 'high',
            })
            expect(out).toEqual({ value: 24576, clamped: null })
        })

        it('honors the spec value when below all ceilings', () => {
            const out = resolveMaxOutputTokens({
                modelMaxTokens: 32_000,
                configOverride: undefined,
                specRequested: 12_000,
                reasoning: undefined,
            })
            expect(out).toEqual({ value: 12_000, clamped: null })
        })

        it('clamps to the model ceiling and reports source=model', () => {
            const out = resolveMaxOutputTokens({
                modelMaxTokens: 8_000,
                configOverride: undefined,
                specRequested: 50_000,
                reasoning: undefined,
            })
            expect(out).toEqual({ value: 8_000, clamped: { requested: 50_000, ceiling: 8_000, source: 'model' } })
        })

        it('clamps to the config override when it is lower than the model', () => {
            const out = resolveMaxOutputTokens({
                modelMaxTokens: 64_000,
                configOverride: 4_000,
                specRequested: 12_000,
                reasoning: undefined,
            })
            expect(out).toEqual({ value: 4_000, clamped: { requested: 12_000, ceiling: 4_000, source: 'config' } })
        })

        it('also clamps the reasoning-aware default when the model is too small', () => {
            const out = resolveMaxOutputTokens({
                modelMaxTokens: 4_096,
                configOverride: undefined,
                specRequested: undefined,
                reasoning: 'high',
            })
            expect(out).toEqual({ value: 4_096, clamped: { requested: 24576, ceiling: 4_096, source: 'model' } })
        })

        it('reports source=model when config and model match exactly', () => {
            const out = resolveMaxOutputTokens({
                modelMaxTokens: 4_000,
                configOverride: 4_000,
                specRequested: 8_000,
                reasoning: undefined,
            })
            expect(out.clamped?.source).toBe('model')
        })
    })
})
