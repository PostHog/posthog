import { pipelineQuestion, pipelineSubtitle, pipelineTitle } from './pipelineQuestion'

describe('pipelineQuestion', () => {
    test.each([
        { target_event: 'file_shared', horizon_days: 30, expected: 'Who will do “file_shared” in the next 30 days?' },
        { target_event: 'file_shared', horizon_days: 1, expected: 'Who will do “file_shared” in the next day?' },
        { target_event: 'file_shared', horizon_days: undefined, expected: 'Who will do “file_shared”?' },
        { target_event: '$pageview', horizon_days: 7, expected: 'Who will do “Pageview” in the next 7 days?' },
    ])('$target_event with horizon $horizon_days', ({ target_event, horizon_days, expected }) => {
        expect(pipelineQuestion({ target_event, horizon_days })).toEqual(expected)
    })

    test.each([
        { name: 'Who will upgrade this month?', expected: 'Who will upgrade this month?' },
        { name: '  Who will upgrade?  ', expected: 'Who will upgrade?' },
        { name: 'Upgrade prediction', expected: 'Who will do “File shared” in the next 7 days?' },
    ])('title for name "$name"', ({ name, expected }) => {
        expect(pipelineTitle({ name, target_event: 'File shared', horizon_days: 7 })).toEqual(expected)
    })

    test.each([
        { name: 'File sharers', expected: 'File sharers' },
        { name: 'Feature adoption: File shared', expected: 'Feature adoption: File shared' },
        { name: 'Who will do File shared in the next 7 days', expected: null },
        { name: 'Who will upgrade this month?', expected: null },
        { name: 'file shared', expected: null },
        { name: 'File', expected: null },
        { name: 'Files', expected: 'Files' },
        { name: '  ', expected: null },
    ])('subtitle for name "$name"', ({ name, expected }) => {
        expect(pipelineSubtitle({ name, target_event: 'File shared', horizon_days: 7 })).toEqual(expected)
    })
})
