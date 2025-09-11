import { parseEncodedSnapshots } from 'scenes/session-recordings/player/snapshot-processing/process-all-snapshots'

import { encodedWebSnapshotData } from './__mocks__/encoded-snapshot-data'

describe('snapshot parsing', () => {
    const sessionId = '12345'
    const numberOfParsedLinesInData = 3

    it('handles normal mobile data', async () => {
        const parsed = await parseEncodedSnapshots(encodedWebSnapshotData, sessionId)
        expect(parsed.length).toEqual(numberOfParsedLinesInData)
        expect(parsed).toMatchSnapshot()
    })
    it('handles mobile data with no meta event', async () => {
        const withoutMeta = [encodedWebSnapshotData[0], encodedWebSnapshotData[2]]
        const parsed = await parseEncodedSnapshots(withoutMeta, sessionId)
        expect(parsed.length).toEqual(numberOfParsedLinesInData)
        expect(parsed).toMatchSnapshot()
    })
})
