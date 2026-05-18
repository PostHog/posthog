import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { PipelineResultType } from '../pipelines/results'
import { createFlushHogTransformerStep } from './flush-hog-transformer-step'

describe('createFlushHogTransformerStep', () => {
    it('calls processInvocationResults and passes input through', async () => {
        const processInvocationResults = jest.fn().mockResolvedValue(undefined)
        const hogTransformer = { processInvocationResults } as unknown as HogTransformerService

        const step = createFlushHogTransformerStep({ hogTransformer })
        const input = { elements: [], batchContext: { foo: 'bar' } }

        const result = await step(input)

        expect(processInvocationResults).toHaveBeenCalledTimes(1)
        expect(result).toMatchObject({ type: PipelineResultType.OK, value: input })
    })
})
