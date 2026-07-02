import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { sidePanelStateLogic } from '~/layout/navigation/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { OrganizationBasicType, Region, SidePanelTab, TeamPublicType } from '~/types'

import { getPublicSupportSnippet, supportLogic } from './supportLogic'
import * as SupportModal from './SupportModal'

// supportLogic and SupportModal import each other, so jest.mock('./SupportModal') leaves supportLogic
// bound to the real openSupportModal — spy on the live module export instead so the call is intercepted.
const openSupportModal = jest.spyOn(SupportModal, 'openSupportModal').mockImplementation(() => {})

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

    describe('openSupportForm modal vs side panel target', () => {
        let logic: ReturnType<typeof supportLogic.build>

        beforeEach(() => {
            // sidePanelStateLogic persists its selected tab and reflects open state in the URL hash;
            // initKeaTests resets neither, so clear them to keep the gating decision deterministic.
            localStorage.clear()
            window.history.replaceState(null, '', '/')
            initKeaTests()
            sidePanelStateLogic.mount()
            logic = supportLogic.build()
            logic.mount()
            openSupportModal.mockClear()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('opens the side panel when target is sidePanel', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSupportForm({ kind: 'support', target_area: 'login', target: 'sidePanel' })
            }).toFinishAllListeners()

            expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
            expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Support)
            expect(openSupportModal).not.toHaveBeenCalled()
        })

        it('opens the modal when target is modal', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSupportForm({ kind: 'support', target_area: 'login', target: 'modal' })
            }).toFinishAllListeners()

            expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
            expect(openSupportModal).toHaveBeenCalledTimes(1)
        })

        it('falls back to sidePanelAvailable when no target is given', async () => {
            sidePanelStateLogic.actions.setSidePanelAvailable(false)
            await expectLogic(logic, () => {
                logic.actions.openSupportForm({ kind: 'support', target_area: 'login' })
            }).toFinishAllListeners()

            expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
            expect(openSupportModal).toHaveBeenCalledTimes(1)
        })
    })
})
