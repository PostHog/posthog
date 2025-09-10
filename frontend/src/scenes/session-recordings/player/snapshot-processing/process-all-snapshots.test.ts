import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { SessionRecordingSnapshotSource } from '~/types'

import { hasAnyWireframes, parseEncodedSnapshots, processAllSnapshots } from './process-all-snapshots'
import { keyForSource } from './source-key'

const pathForKeyZero = join(__dirname, '../__mocks__/perf-snapshot-key0.jsonl')

const readFileContents = (path: string): string => {
    return readFileSync(path, 'utf-8')
}

const keyZero = readFileContents(pathForKeyZero)
// const keyOne = readFileContents(pathForKeyOne)

describe('process all snapshots', () => {
    describe('performance check', () => {
        it('can process all snapshots fast', async () => {
            const sessionId = '1234'
            const source = {
                source: 'blob_v2',
                blob_key: '0',
            } as SessionRecordingSnapshotSource
            const key = keyForSource(source)
            const rawSnapshots = keyZero.split('\n')
            const snapshots = await parseEncodedSnapshots(rawSnapshots, sessionId)
            expect(snapshots).toHaveLength(100)

            const start = performance.now()
            const results = processAllSnapshots(
                [
                    {
                        source: 'blob_v2',
                        blob_key: '0',
                    },
                ],
                {
                    [key]: {
                        snapshots: snapshots,
                    },
                },
                {},
                () => {
                    return {
                        width: '100',
                        height: '100',
                        href: 'https://example.com',
                    }
                },
                sessionId
            )
            const end = performance.now()
            const duration = end - start
            expect(results.length).toBe(99)
            expect(duration).toBeLessThan(10)
        })
    })

    describe('hasAnyWireframes', () => {
        it('can detect a react native sdk 4.1.0 updates wireframe', () => {
            expect(
                hasAnyWireframes([
                    {
                        timestamp: 1751925097543,
                        data: {
                            source: 0,
                            updates: [
                                {
                                    wireframe: {
                                        base64: 'data:image/webp;base64,blahblah\n',
                                        height: 904,
                                        id: 172905027,
                                        style: {},
                                        type: 'screenshot',
                                        width: 406,
                                        x: 0,
                                        y: 0,
                                    },
                                },
                            ],
                        },
                        type: 3,
                    },
                ])
            ).toBeTruthy()
        })
    })
})
