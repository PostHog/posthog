import { EventType, IncrementalSource } from 'posthog-js/rrweb-types'

import { RecordingSnapshot, SessionRecordingSnapshotSource } from '../types'
import { MUTATION_CHUNK_SIZE } from './chunk-large-mutations'
import { parseJsonSnapshots, processAllSnapshots } from './process-all-snapshots'
import { sortSnapshots } from './sort-snapshots'
import { keyForSource } from './source-key'
import { clearThrottle } from './throttle-capturing'

const SESSION_ID = 'ordering-session'
const SOURCE: SessionRecordingSnapshotSource = { source: 'blob_v2', blob_key: '0' }
const VIEWPORT = { width: '100', height: '100', href: 'https://example.com' }

const textMutation = (timestamp: number, id: number, value: string, seq?: number): RecordingSnapshot =>
    ({
        windowId: 1,
        timestamp,
        seq,
        type: EventType.IncrementalSnapshot,
        data: { source: IncrementalSource.Mutation, adds: [], removes: [], attributes: [], texts: [{ id, value }] },
    }) as unknown as RecordingSnapshot

const runProcessing = (snapshots: RecordingSnapshot[]): Promise<RecordingSnapshot[]> =>
    processAllSnapshots(
        [SOURCE],
        { [keyForSource(SOURCE)]: { snapshots } },
        { snapshots: {} },
        () => VIEWPORT,
        SESSION_ID
    )

const textValuesFor = (snapshots: RecordingSnapshot[], id: number): string[] =>
    snapshots.flatMap((snapshot) =>
        ((snapshot.data as any)?.texts ?? [])
            .filter((text: { id: number }) => text.id === id)
            .map((text: { value: string }) => text.value)
    )

describe('snapshot ordering', () => {
    beforeEach(() => {
        clearThrottle()
    })

    it('keeps a text value that is re-set within the same millisecond', async () => {
        // rrweb applies texts by node id, last write wins, so dropping the third event as a
        // "duplicate" of the first leaves the node showing the masked placeholder instead of the name.
        const results = await runProcessing([
            textMutation(1000, 42, 'Jane'),
            textMutation(1000, 42, 'REDACTED'),
            textMutation(1000, 42, 'Jane'),
        ])

        expect(textValuesFor(results, 42)).toEqual(['Jane', 'REDACTED', 'Jane'])
    })

    it('drops an event that is byte-identical to its immediate neighbour', async () => {
        const results = await runProcessing([textMutation(1000, 42, 'Jane'), textMutation(1000, 42, 'Jane')])

        expect(textValuesFor(results, 42)).toEqual(['Jane'])
    })

    it('drops a whole millisecond that was written twice', async () => {
        const run = [textMutation(1000, 42, 'Jane'), textMutation(1000, 43, 'Doe')]
        const results = await runProcessing([...run, ...run])

        expect(results).toHaveLength(2)
    })

    it('keeps every chunk of an oversized mutation even when two chunks are identical', async () => {
        // Three chunks of identical placeholder nodes: the middle one carries no removes, texts or
        // attributes, which makes it byte-identical to the first. Dropping it would leave the nodes
        // that the last chunk's `texts` target missing from the DOM.
        const adds = Array.from({ length: MUTATION_CHUNK_SIZE * 3 }, () => ({
            parentId: 1,
            nextId: null,
            node: { type: 2, tagName: 'td', attributes: {}, childNodes: [], id: 7 },
        }))
        const oversizedMutation = {
            windowId: 1,
            timestamp: 1000,
            type: EventType.IncrementalSnapshot,
            data: {
                source: IncrementalSource.Mutation,
                adds,
                removes: [],
                attributes: [],
                texts: [{ id: 7, value: 'Jane' }],
            },
        } as unknown as RecordingSnapshot

        const chunks = parseJsonSnapshots([oversizedMutation], SESSION_ID)
        expect(chunks).toHaveLength(3)

        const results = await runProcessing(chunks)

        expect(results).toHaveLength(3)
        expect(textValuesFor(results, 7)).toEqual(['Jane'])
    })

    it('restores capture order for same-millisecond events that arrive out of order', () => {
        const first = textMutation(1000, 42, 'Jane', 10)
        const second = textMutation(1000, 42, 'REDACTED', 11)

        expect(sortSnapshots([second, first])).toEqual([first, second])
    })

    it('sorts synthesized snapshots, which carry no sequence, by insertion position', () => {
        const meta = {
            windowId: 1,
            timestamp: 1000,
            type: EventType.Meta,
            data: VIEWPORT,
        } as unknown as RecordingSnapshot
        const mutation = textMutation(1000, 42, 'Jane', 10)

        expect(sortSnapshots([meta, mutation])).toEqual([meta, mutation])
    })
})
