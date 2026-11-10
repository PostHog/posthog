import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { commandLogic } from 'lib/components/Command/commandLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { COMMAND_K_FLOW } from './inAppOnboardingFlows'
import { inAppOnboardingLogic } from './inAppOnboardingLogic'

describe('inAppOnboardingLogic', () => {
    let logic: ReturnType<typeof inAppOnboardingLogic.build>

    const loadUser = (hasSeenProductIntroFor: Record<string, boolean>): void => {
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            has_seen_product_intro_for: hasSeenProductIntroFor,
        } as UserType)
    }

    // Drives the palette the way a person does, through the command logic rather than the onboarding one.
    const pressCommandK = (): void => commandLogic.actions.toggleCommand('keyboard-shortcut')
    const finishLoading = (): void => commandLogic.actions.commandInputReady()

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        userLogic.mount()
        commandLogic.mount()
        logic = inAppOnboardingLogic()
        logic.mount()
    })

    it('teaches the command k flow by doing each step', async () => {
        loadUser({})

        await expectLogic(logic, () => {
            pressCommandK()
            finishLoading()
        }).toMatchValues({ activeProgress: { stepIndex: 1, count: 0 } })

        await expectLogic(logic, () => {
            commandLogic.actions.closeCommand()
        }).toMatchValues({ activeProgress: { stepIndex: 2, count: 0 } })

        // The same shortcut opens and closes, so practising three opens takes five presses.
        await expectLogic(logic, () => {
            pressCommandK()
            pressCommandK()
            pressCommandK()
        }).toMatchValues({ activeProgress: { stepIndex: 2, count: 2 } })

        await expectLogic(logic, () => {
            pressCommandK()
            pressCommandK()
            logic.actions.recordSignal('command-result-opened')
        })
            .toDispatchActions([
                'completeFlow',
                userLogic.actionCreators.updateHasSeenProductIntroFor(COMMAND_K_FLOW.seenKey),
            ])
            .toMatchValues({ isActiveFlowComplete: true, activeFlow: COMMAND_K_FLOW })
    })

    it('does not count opening search with the mouse', async () => {
        loadUser({})

        await expectLogic(logic, () => {
            commandLogic.actions.toggleCommand('nav-search-button')
        }).toMatchValues({ activeProgress: { stepIndex: 0, count: 0 } })
    })

    it.each([
        ['the user has not loaded', null],
        ['the user already finished or skipped it', { [COMMAND_K_FLOW.seenKey]: true }],
    ])('shows nothing when %s', async (_label, seen) => {
        if (seen) {
            loadUser(seen)
        } else {
            userLogic.actions.loadUserSuccess(null)
        }

        await expectLogic(logic).toMatchValues({ activeFlow: null })
    })

    it('hides the flow and records it as seen when skipped', async () => {
        loadUser({})

        await expectLogic(logic, () => {
            logic.actions.skipFlow(COMMAND_K_FLOW.key)
        })
            .toDispatchActions([userLogic.actionCreators.updateHasSeenProductIntroFor(COMMAND_K_FLOW.seenKey)])
            .toMatchValues({ activeFlow: null })
    })
})
