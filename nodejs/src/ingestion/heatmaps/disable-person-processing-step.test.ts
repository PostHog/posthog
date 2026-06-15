import { PipelineResultType } from '../pipelines/results'
import { createDisablePersonProcessingStep } from './disable-person-processing-step'

describe('disablePersonProcessingStep', () => {
    it('sets processPerson to false', async () => {
        const step = createDisablePersonProcessingStep()
        const input = {
            someField: 'value',
            anotherField: 123,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value).toEqual({
                someField: 'value',
                anotherField: 123,
                processPerson: false,
            })
        }
    })

    it('overrides existing processPerson value', async () => {
        const step = createDisablePersonProcessingStep()
        const input = {
            someField: 'value',
            processPerson: true,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value).toEqual({
                someField: 'value',
                processPerson: false,
            })
        }
    })

    it('preserves all other input fields', async () => {
        const input = {
            field1: 'value1',
            field2: 'value2',
            field3: 123,
            field4: { nested: 'object' },
            field5: ['array', 'values'],
        }
        const step = createDisablePersonProcessingStep<typeof input>()

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value).toEqual({
                ...input,
                processPerson: false,
            })
            const value = result.value
            expect(value.field1).toBe('value1')
            expect(value.field2).toBe('value2')
            expect(value.field3).toBe(123)
            expect(value.field4).toEqual({ nested: 'object' })
            expect(value.field5).toEqual(['array', 'values'])
        }
    })
})
