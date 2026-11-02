import { initKeaTests } from '~/test/init'

import { replayListColumnLogic } from './replayListColumnLogic'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

describe('replayListColumnLogic', () => {
    let logic: ReturnType<typeof replayListColumnLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = replayListColumnLogic({ logicKey: 'test' })
        logic.mount()
    })

    it.each([
        { chosen: null, picksMode: null, expected: 'recordings' },
        { chosen: null, picksMode: 'picks', expected: 'picks' },
        { chosen: 'recordings', picksMode: 'picks', expected: 'recordings' },
        { chosen: 'picks', picksMode: null, expected: 'recordings' },
        { chosen: 'collections', picksMode: null, expected: 'collections' },
    ] as const)('chosen $chosen with picks $picksMode shows $expected', ({ chosen, picksMode, expected }) => {
        if (chosen) {
            logic.actions.setSegment(chosen)
        }
        expect(logic.values.effectiveSegmentFor(picksMode)).toBe(expected)
    })

    it.each([
        { picksMode: 'picks', kept: 'picks' },
        { picksMode: null, kept: null },
    ] as const)('a picks choice settles to $kept with picks $picksMode', ({ picksMode, kept }) => {
        logic.actions.setSegment('picks')
        logic.actions.settleSegment(picksMode)
        expect(logic.values.segment).toBe(kept)
    })

    it.each([
        ['closes when the viewer goes back', (l: typeof logic) => l.actions.closeCollection()],
        ['closes when the segment changes', (l: typeof logic) => l.actions.setSegment('recordings')],
    ])('an open collection %s', (_, act) => {
        logic.actions.openCollection('abc')
        expect(logic.values.openCollectionShortId).toBe('abc')
        act(logic)
        expect(logic.values.openCollectionShortId).toBeNull()
    })

    it('shows the recordings when its list is filtered to a person', () => {
        const playlistLogicProps = { logicKey: 'person' }
        const column = replayListColumnLogic({ logicKey: 'person', playlistLogicProps })
        column.mount()
        column.actions.setSegment('picks')
        sessionRecordingsPlaylistLogic(playlistLogicProps).actions.filterByPerson('p')
        expect(column.values.segment).toBe('recordings')
    })
})
