import { createHogExecutionGlobals } from '../_tests/fixtures'
import { HogFunctionInvocationGlobalsSchema } from './cyclotron'

describe('cyclotron schema', () => {
    describe('HogFunctionInvocationGlobalsSchema', () => {
        it('accepts well-formed globals', () => {
            const globals = createHogExecutionGlobals({})
            expect(HogFunctionInvocationGlobalsSchema.safeParse(globals).success).toBe(true)
        })

        it.each([['project'], ['event']] as const)('rejects globals missing %s (poison-pill shape)', (field) => {
            const globals = createHogExecutionGlobals({}) as any
            delete globals[field]
            expect(HogFunctionInvocationGlobalsSchema.safeParse(globals).success).toBe(false)
        })

        it.each([
            { mutation: (g: any) => (g.project.id = 'not-a-number'), desc: 'project.id is not a number' },
            { mutation: (g: any) => delete g.project.url, desc: 'project.url is missing' },
            { mutation: (g: any) => delete g.event.distinct_id, desc: 'event.distinct_id is missing' },
            { mutation: (g: any) => delete g.event.properties, desc: 'event.properties is missing' },
        ])('rejects when $desc', ({ mutation }) => {
            const globals = createHogExecutionGlobals({}) as any
            mutation(globals)
            expect(HogFunctionInvocationGlobalsSchema.safeParse(globals).success).toBe(false)
        })

        it('passes through non-critical fields so reruns keep inputs/request', () => {
            // The rerun path casts the validated globals to WithInputs and relies on
            // extra fields surviving — a switch to a strict schema would silently
            // strip them and break replay.
            const globals = { ...createHogExecutionGlobals({}), inputs: { url: 'https://x' }, custom: 1 } as any
            const parsed = HogFunctionInvocationGlobalsSchema.safeParse(globals)
            expect(parsed.success).toBe(true)
            expect((parsed as any).data.inputs).toEqual({ url: 'https://x' })
            expect((parsed as any).data.custom).toBe(1)
        })
    })
})
