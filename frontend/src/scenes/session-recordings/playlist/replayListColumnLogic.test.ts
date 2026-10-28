import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { SessionRecordingSidebarTab } from '~/types'

import { playerSidebarLogic } from '../player/sidebar/playerSidebarLogic'
import { replayListColumnLogic } from './replayListColumnLogic'

describe('replayListColumnLogic', () => {
    let logic: ReturnType<typeof replayListColumnLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = replayListColumnLogic({ logicKey: 'test' })
        logic.mount()
    })

    it.each([
        { chosen: null, picksMode: null, moments: false, expected: 'recordings' },
        { chosen: null, picksMode: 'picks', moments: false, expected: 'picks' },
        { chosen: null, picksMode: 'picks', moments: true, expected: 'picks' },
        { chosen: null, picksMode: null, moments: true, expected: 'recordings' },
        { chosen: 'recordings', picksMode: null, moments: true, expected: 'recordings' },
        { chosen: 'picks', picksMode: null, moments: false, expected: 'recordings' },
        { chosen: 'moments', picksMode: 'picks', moments: true, expected: 'moments' },
        { chosen: 'moments', picksMode: 'picks', moments: false, expected: 'recordings' },
        { chosen: 'moments', picksMode: null, moments: null, expected: 'recordings' },
        { chosen: 'recordings', picksMode: 'picks', moments: true, expected: 'recordings' },
    ] as const)(
        'chosen $chosen with picks $picksMode and moments $moments shows $expected',
        ({ chosen, picksMode, moments, expected }) => {
            if (chosen) {
                logic.actions.setSegment(chosen)
            }
            expect(logic.values.effectiveSegmentFor(picksMode, moments)).toBe(expected)
        }
    )

    it.each([
        { chosen: 'moments', picksMode: null, moments: null, kept: 'moments' },
        { chosen: 'moments', picksMode: null, moments: true, kept: 'moments' },
        { chosen: 'moments', picksMode: null, moments: false, kept: null },
        { chosen: 'picks', picksMode: 'picks', moments: null, kept: 'picks' },
        { chosen: 'picks', picksMode: null, moments: null, kept: null },
    ] as const)(
        'chosen $chosen settles to $kept with picks $picksMode and moments $moments',
        ({ chosen, picksMode, moments, kept }) => {
            logic.actions.setSegment(chosen)
            logic.actions.settleSegment(picksMode, moments)
            expect(logic.values.segment).toBe(kept)
        }
    )

    it('switches to moments when something asks for the observations tab', async () => {
        await expectLogic(logic, () => {
            playerSidebarLogic.actions.setTab(SessionRecordingSidebarTab.OBSERVATIONS)
        }).toMatchValues({ segment: 'moments' })
    })
})
