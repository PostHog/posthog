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
        { chosen: null, picksMode: 'picks', moments: true, expected: 'moments' },
        { chosen: 'recordings', picksMode: null, moments: true, expected: 'recordings' },
        { chosen: 'picks', picksMode: null, moments: false, expected: 'recordings' },
        { chosen: 'moments', picksMode: 'picks', moments: true, expected: 'moments' },
        { chosen: 'moments', picksMode: 'picks', moments: false, expected: 'recordings' },
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

    it('switches to moments when something asks for the observations tab', async () => {
        await expectLogic(logic, () => {
            playerSidebarLogic.actions.setTab(SessionRecordingSidebarTab.OBSERVATIONS)
        }).toMatchValues({ segment: 'moments' })
    })
})
