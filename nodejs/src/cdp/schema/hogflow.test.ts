import { HogFlowActionSchema, HogFlowSchema } from './hogflow'

describe('hogflow schema', () => {
    const commonActionFields = {
        id: 'action-1',
        name: 'Wait',
        description: '',
        created_at: 0,
        updated_at: 0,
        filters: {},
    }

    describe('wait_until_condition events', () => {
        const baseConfig = {
            condition: { filters: {} },
            max_wait_duration: '5m',
        }

        it('accepts a wait_until_condition action with an events list', () => {
            const parsed = HogFlowActionSchema.parse({
                ...commonActionFields,
                type: 'wait_until_condition',
                config: {
                    ...baseConfig,
                    events: [{ filters: { bytecode: ['_H', 1] }, name: 'pricing_viewed' }],
                },
            })
            expect(parsed.type).toBe('wait_until_condition')
            expect((parsed.config as any).events).toHaveLength(1)
        })

        it('accepts a wait_until_condition action without an events list (optional)', () => {
            const parsed = HogFlowActionSchema.parse({
                ...commonActionFields,
                type: 'wait_until_condition',
                config: baseConfig,
            })
            expect((parsed.config as any).events).toBeUndefined()
        })
    })

    describe('output_variable legacy string normalization', () => {
        it.each([
            ['bare string', 'greeting', { key: 'greeting' }],
            ['string in a list', ['greeting', { key: 'other' }], [{ key: 'greeting' }, { key: 'other' }]],
            ['canonical object', { key: 'greeting', result_path: 'r' }, { key: 'greeting', result_path: 'r' }],
        ])('parses %s to the canonical shape', (_name, stored, expected) => {
            const parsed = HogFlowActionSchema.parse({
                ...commonActionFields,
                type: 'delay',
                config: { delay_duration: '5m' },
                output_variable: stored,
            })
            expect(parsed.output_variable).toEqual(expected)
        })
    })

    describe('conversion events', () => {
        const baseHogFlow = {
            id: 'flow-1',
            team_id: 1,
            version: 1,
            name: 'Test',
            status: 'active' as const,
            trigger: { type: 'event' as const, filters: {} },
            exit_condition: 'exit_only_at_end' as const,
            actions: [],
            edges: [],
        }

        it('accepts a conversion goal with an events list', () => {
            const parsed = HogFlowSchema.parse({
                ...baseHogFlow,
                conversion: {
                    window_minutes: 60,
                    filters: {},
                    bytecode: [],
                    events: [{ filters: { bytecode: ['_H', 1] }, name: 'subscribed' }],
                },
            })
            expect(parsed.conversion?.events).toHaveLength(1)
        })

        it('accepts a conversion goal without an events list (optional)', () => {
            const parsed = HogFlowSchema.parse({
                ...baseHogFlow,
                conversion: { window_minutes: 60, filters: {}, bytecode: [] },
            })
            expect(parsed.conversion?.events).toBeUndefined()
        })
    })
})
