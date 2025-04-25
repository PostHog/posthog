import { SEGMENT_DESTINATIONS } from './segmentTemplates'
import { LegacyDestinationPlugin } from './types'

const destinationEntries = Object.entries(SEGMENT_DESTINATIONS).filter(([_, destination]) => destination.template)

const testCases = destinationEntries.map(([_, destination]) => ({
    id: destination.template?.id,
    destination: destination as LegacyDestinationPlugin,
}))

describe('segment templates', () => {
    test.each(testCases)('template $id matches expected result', ({ destination }) => {
        expect(destination.template).toMatchSnapshot()
    })
})
