import { SEGMENT_DESTINATIONS } from './segmentTemplates'

const destinationEntries = Object.entries(SEGMENT_DESTINATIONS).filter(([_, destination]) => destination.template)

const testCases = destinationEntries.map(([_, destination]) => ({
    id: destination.template?.id,
    destination,
}))

describe('segment templates', () => {
    test.each(testCases)('template $id matches expected result', ({ destination }) => {
        expect(destination.template).toMatchSnapshot()
    })
})
