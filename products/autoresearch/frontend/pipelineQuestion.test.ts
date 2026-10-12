import { pipelineQuestion } from './pipelineQuestion'

describe('pipelineQuestion', () => {
    test.each([
        { horizon_days: 30, expected: 'Who will do file_shared in the next 30 days?' },
        { horizon_days: 1, expected: 'Who will do file_shared in the next day?' },
        { horizon_days: undefined, expected: 'Who will do file_shared?' },
    ])('horizon $horizon_days', ({ horizon_days, expected }) => {
        expect(pipelineQuestion({ target_event: 'file_shared', horizon_days })).toEqual(expected)
    })
})
