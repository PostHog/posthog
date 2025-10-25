import {
    parseEncodedSnapshots,
    processAllSnapshots,
} from 'scenes/session-recordings/player/snapshot-processing/process-all-snapshots'
import { keyForSource } from 'scenes/session-recordings/player/snapshot-processing/source-key'

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

        const source = { source: 'blob_v2', blob_key: '0' } as any
        const results = processAllSnapshots(
            [source],
            { [keyForSource(source)]: { snapshots: parsed } } as any,
            {},
            () => ({ width: '400', height: '800', href: 'https://example.com' }),
            sessionId
        )

        expect(results.length).toEqual(numberOfParsedLinesInData)
        const meta = results.find((r) => r.type === 4)!
        // Mobile snapshots now extract dimensions from the actual snapshot data (393x852)
        // rather than using the viewport callback, which is the correct behavior
        expect(meta.data).toEqual({ width: 393, height: 852, href: 'unknown' })
        // Should include at least one full or incremental afterward
        expect(results.some((r) => r.type === 2 || r.type === 3)).toBe(true)
        // Preserve total count
        expect(results.length).toEqual(numberOfParsedLinesInData)
    })
})
