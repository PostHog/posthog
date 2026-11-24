import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { type SessionRecordingMaskingConfig } from '~/types'

import { ReplayMaskingSettings } from './SessionRecordingSettings'

const TEXT_SWITCH = 'replay-mobile-mask-all-text-switch'
const IMAGES_SWITCH = 'replay-mobile-mask-all-images-switch'

describe('<ReplayMaskingSettings />', () => {
    let patchBodies: Record<string, unknown>[]
    const originalPointerEvent = window.PointerEvent

    beforeAll(() => {
        // jsdom has no PointerEvent, and the quill Switch constructs one on click.
        window.PointerEvent = MouseEvent as typeof PointerEvent
    })

    afterAll(() => {
        window.PointerEvent = originalPointerEvent
    })

    beforeEach(() => {
        patchBodies = []
        useMocks({
            patch: {
                '/api/projects/:id': async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    patchBodies.push(body)
                    return [200, { ...MOCK_DEFAULT_TEAM, ...body }]
                },
            },
        })
        initKeaTests()
        teamLogic.mount()
        featureFlagLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    const renderWithConfig = (
        config: SessionRecordingMaskingConfig | null,
        todayRailNav: boolean,
        membershipLevel: OrganizationMembershipLevel = OrganizationMembershipLevel.Admin
    ): HTMLElement => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            session_recording_masking_config: config,
            effective_membership_level: membershipLevel,
        })
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: todayRailNav,
        })
        return render(<ReplayMaskingSettings />).container
    }

    const findSwitch = (container: HTMLElement, dataAttr: string): HTMLElement => {
        const element = container.querySelector<HTMLElement>(`[data-attr="${dataAttr}"]`)
        if (!element) {
            throw new Error(`No switch with data-attr ${dataAttr}`)
        }
        return element
    }

    describe.each([
        ['default navigation', false],
        ['today rail navigation', true],
    ])('with %s', (_name, todayRailNav) => {
        it.each<[string, SessionRecordingMaskingConfig | null, string, SessionRecordingMaskingConfig['mobile']]>([
            ['sends true for a switch that is turned on', null, TEXT_SWITCH, { maskAllText: true }],
            [
                'keeps the web keys and the other switch out of the request',
                { maskAllInputs: true, maskTextSelector: '*', mobile: { maskAllText: true } },
                IMAGES_SWITCH,
                { maskAllImages: true },
            ],
            [
                'sends false for a switch that is turned off',
                { mobile: { maskAllText: true, maskAllImages: true } },
                IMAGES_SWITCH,
                { maskAllImages: false },
            ],
            [
                'shows a stored false as off and turns it on',
                { mobile: { maskAllText: false, maskAllImages: true } },
                TEXT_SWITCH,
                { maskAllText: true },
            ],
        ])('%s', async (_case, storedConfig, dataAttr, expectedMobile) => {
            const container = renderWithConfig(storedConfig, todayRailNav)

            expect(findSwitch(container, TEXT_SWITCH)).toHaveAttribute(
                'aria-checked',
                String(storedConfig?.mobile?.maskAllText === true)
            )
            expect(findSwitch(container, IMAGES_SWITCH)).toHaveAttribute(
                'aria-checked',
                String(storedConfig?.mobile?.maskAllImages === true)
            )

            fireEvent.click(findSwitch(container, dataAttr))

            await waitFor(() => expect(patchBodies).toHaveLength(1))
            expect(patchBodies[0]).toEqual({ session_recording_masking_config: { mobile: expectedMobile } })
        })

        it('sends no request when a member without admin access clicks a switch', async () => {
            const container = renderWithConfig(null, todayRailNav, OrganizationMembershipLevel.Member)

            fireEvent.click(findSwitch(container, TEXT_SWITCH))

            await expectLogic(teamLogic).toNotHaveDispatchedActions(['updateCurrentTeam'])
            expect(patchBodies).toHaveLength(0)
        })
    })
})
