import { UserRole } from '~/types'

import { MCP_INSTALL_COMMAND } from './constants'
import { buildMCPAgentPrompt, FALLBACK_PROMPTS, formatDerivedToastPrompt, getSurfacePrompts } from './prompts'

describe('prompts', () => {
    describe('getSurfacePrompts', () => {
        it('applies a tailored role override', () => {
            const tailored = getSurfacePrompts('sql.execute', { role: UserRole.Engineering })
            expect(tailored.toast).toBe('"How many users hit a 500 in the last hour?"')
            expect(tailored.toast).not.toBe(FALLBACK_PROMPTS['sql.execute'].toast)
        })

        it('falls back to defaults for non-tailored and missing roles', () => {
            expect(getSurfacePrompts('sql.execute', { role: UserRole.Sales })).toEqual(FALLBACK_PROMPTS['sql.execute'])
            expect(getSurfacePrompts('sql.execute', { role: null })).toEqual(FALLBACK_PROMPTS['sql.execute'])
            expect(getSurfacePrompts('sql.execute')).toEqual(FALLBACK_PROMPTS['sql.execute'])
        })

        it('weaves real event names into SQL examples, dropping internal ones', () => {
            const { examples } = getSurfacePrompts('sql.execute', {
                topEvents: ['$pageview', 'signup_completed', 'checkout_started', 'purchase'],
            })
            expect(examples).toEqual([
                '"How many users triggered signup_completed yesterday?"',
                '"What\'s the trend of checkout_started over the last 30 days?"',
                '"Funnel: signup_completed → checkout_started → purchase"',
            ])
        })

        it('keeps static SQL examples when every event is internal', () => {
            const { examples } = getSurfacePrompts('sql.execute', {
                topEvents: ['$pageview', '$identify', '$autocapture'],
            })
            expect(examples).toEqual(FALLBACK_PROMPTS['sql.execute'].examples)
        })

        it('ignores topEvents for non-SQL surfaces', () => {
            const { examples } = getSurfacePrompts('insights.create', { topEvents: ['signup_completed'] })
            expect(examples).toEqual(FALLBACK_PROMPTS['insights.create'].examples)
        })
    })

    describe('formatDerivedToastPrompt', () => {
        it('wraps bare and pre-quoted prompts identically in straight double quotes', () => {
            expect(formatDerivedToastPrompt('foo')).toBe('"foo"')
            expect(formatDerivedToastPrompt('"foo"')).toBe('"foo"')
            expect(formatDerivedToastPrompt("'foo'")).toBe('"foo"')
        })

        it('trims surrounding whitespace before quoting', () => {
            expect(formatDerivedToastPrompt('  foo  ')).toBe('"foo"')
        })
    })

    describe('buildMCPAgentPrompt', () => {
        it.each([
            [42, 'Use the PostHog MCP server in PostHog project 42.'],
            [null, 'Use the PostHog MCP server.'],
        ])(
            'sends the task without display quotes and tells the agent how to connect (project %s)',
            (projectId, mcpLine) => {
                const prompt = buildMCPAgentPrompt('"Disable beta-banner flag"', projectId)
                expect(prompt.startsWith('Disable beta-banner flag\n')).toBe(true)
                expect(prompt).toContain(mcpLine)
                expect(prompt).toContain(MCP_INSTALL_COMMAND)
            }
        )
    })
})
