import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { OrganizationBasicType, Region, SidePanelTab, TeamPublicType } from '~/types'

import { getPublicSupportSnippet, supportLogic } from './supportLogic'
import { openSupportModal } from './SupportModal'

jest.mock('./SupportModal', () => ({ openSupportModal: jest.fn() }))

describe('supportLogic', () => {
    describe('snippet helpers', () => {
        const mockedGetReplayUrl = posthog.get_session_replay_url as jest.Mock
        const organization = { id: 'org-1', name: 'Test org' } as OrganizationBasicType
        const team = { id: 42 } as TeamPublicType

        beforeEach(() => {
            mockedGetReplayUrl.mockReset()
        })

        it('rewrites the session line to the internal golink for staff triage', () => {
            mockedGetReplayUrl.mockReturnValue(`${window.location.origin}/replay/abc?t=30`)
            const snippet = getPublicSupportSnippet(Region.US, organization, team, false)
            expect(snippet).toContain('Session: http://go/session/abc?t=30')
            expect(snippet).not.toContain(`${window.location.origin}/replay/`)
        })

        it('omits the session line when there is no recording', () => {
            mockedGetReplayUrl.mockReturnValue(undefined)
            const snippet = getPublicSupportSnippet(Region.US, organization, team, false)
            expect(snippet).not.toContain('Session:')
        })

        it('marks the admin line as internal', () => {
            mockedGetReplayUrl.mockReturnValue(undefined)
            const snippet = getPublicSupportSnippet(Region.US, organization, team, false)
            expect(snippet).toContain('Admin (internal): http://go/adminOrg')
        })
    })

    describe('modal vs side panel gating', () => {
        let logic: ReturnType<typeof supportLogic.build>

        beforeEach(() => {
            initKeaTests()
            featureFlagLogic.mount()
            sidePanelStateLogic.mount()
            navigation3000Logic.mount()
            logic = supportLogic.build()
            logic.mount()
            ;(openSupportModal as jest.Mock).mockClear()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('opens the support side panel on full-mode scenes', async () => {
            // The default test scene is not a plain layout, so the nav is in full mode and the panel exists.
            await expectLogic(logic).toMatchValues({ mode: 'full' })

            await expectLogic(logic, () => {
                logic.actions.openSupportForm({ kind: 'support', target_area: 'login' })
            }).toFinishAllListeners()

            expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
            expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Support)
            expect(openSupportModal).not.toHaveBeenCalled()
        })

        it('falls back to the modal on scenes without a side panel', async () => {
            // Zen mode is one of the modes that never mounts the side panel.
            navigation3000Logic.actions.setZenMode(true)
            await expectLogic(logic).toMatchValues({ mode: 'zen' })

            await expectLogic(logic, () => {
                logic.actions.openSupportForm({ kind: 'support', target_area: 'login' })
            }).toFinishAllListeners()

            expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
            expect(openSupportModal).toHaveBeenCalledTimes(1)
        })
    })
})
