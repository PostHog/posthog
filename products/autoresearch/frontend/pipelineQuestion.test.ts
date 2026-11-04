import { pipelineQuestion, pipelineSubtitle } from './pipelineQuestion'

describe('pipelineQuestion', () => {
    test.each([
        { horizon_days: 30, expected: 'Who will do “file_shared” in the next 30 days?' },
        { horizon_days: 1, expected: 'Who will do “file_shared” in the next day?' },
        { horizon_days: undefined, expected: 'Who will do “file_shared”?' },
    ])('horizon $horizon_days', ({ horizon_days, expected }) => {
        expect(pipelineQuestion({ target_event: 'file_shared', horizon_days })).toEqual(expected)
    })

    test.each([
        { name: 'File sharers', expected: 'File sharers' },
        { name: 'Feature adoption: File shared', expected: 'Feature adoption: File shared' },
        { name: 'Who will do File shared in the next 7 days', expected: null },
        { name: 'file shared', expected: null },
        { name: 'File', expected: null },
        { name: 'Files', expected: 'Files' },
        { name: '  ', expected: null },
    ])('subtitle for name "$name"', ({ name, expected }) => {
        expect(pipelineSubtitle({ name, target_event: 'File shared', horizon_days: 7 })).toEqual(expected)
    })
})
