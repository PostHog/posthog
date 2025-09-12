import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { featureFlagConfirmationSettingsLogic } from './featureFlagConfirmationSettingsLogic'

describe('featureFlagConfirmationSettingsLogic', () => {
    let logic: ReturnType<typeof featureFlagConfirmationSettingsLogic.build>
    let lastCapturedPayload: any = null

    beforeEach(() => {
        lastCapturedPayload = null
        useMocks({
            patch: {
                '/api/environments/:id': async (req, res, ctx) => {
                    lastCapturedPayload = await req.json()
                    const updatedTeam = { ...MOCK_DEFAULT_TEAM, ...lastCapturedPayload }
                    return res(ctx.json(updatedTeam))
                },
            },
        })
        initKeaTests()
        logic = featureFlagConfirmationSettingsLogic()
        logic.mount()
        // Load mock team data
        teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('form initialization', () => {
        it('initializes with empty message when team has no custom message', async () => {
            await expectLogic(logic).toMatchValues({
                confirmationMessageForm: { message: '' },
            })
        })

        it('initializes with team message when team has custom message', async () => {
            const teamWithMessage = {
                ...MOCK_DEFAULT_TEAM,
                feature_flag_confirmation_message: 'Custom team message',
            }

            teamLogic.actions.loadCurrentTeamSuccess(teamWithMessage)

            await expectLogic(logic).toMatchValues({
                confirmationMessageForm: { message: 'Custom team message' },
            })
        })
    })

    describe('form submission', () => {
        it('submits form and updates team settings', async () => {
            logic.actions.setConfirmationMessageFormValue('message', 'New custom message')

            const promise = logic.actions.submitConfirmationMessageForm()

            await expectLogic(logic)
                .toDispatchActions(['updateConfirmationMessage'])
                .toMatchValues({ confirmationMessageLoading: true })

            await promise

            await expectLogic(logic)
                .toDispatchActions(['updateConfirmationMessageSuccess'])
                .toMatchValues({ confirmationMessageLoading: false })
        })

        it('handles form submission with empty message', async () => {
            logic.actions.setConfirmationMessageFormValue('message', '')

            const promise = logic.actions.submitConfirmationMessageForm()

            await expectLogic(logic).toDispatchActions(['updateConfirmationMessage'])

            await promise

            await expectLogic(logic).toDispatchActions(['updateConfirmationMessageSuccess'])

            // Verify the PATCH request payload contains the empty message
            expect(lastCapturedPayload).toEqual({
                feature_flag_confirmation_message: '',
            })
        })

        it('handles form submission errors correctly', async () => {
            // Override mock to return an error response
            useMocks({
                patch: {
                    '/api/environments/:id': async () => {
                        return [500, { type: 'server_error', detail: 'Internal server error' }]
                    },
                },
            })

            logic.actions.setConfirmationMessageFormValue('message', 'Test message')

            // Start the submission and verify initial loading state
            await expectLogic(logic, () => {
                logic.actions.submitConfirmationMessageForm()
            })
                .toDispatchActions(['updateConfirmationMessage'])
                .toMatchValues({ confirmationMessageLoading: true })

            // Wait for teamLogic to fail
            await expectLogic(logic).toDispatchActions(teamLogic, ['updateCurrentTeamFailure'])

            // Give it a moment for all async operations to complete
            await new Promise((resolve) => setTimeout(resolve, 100))

            // Verify final state - loading should be false and no success toast should show
            await expectLogic(logic).toMatchValues({ confirmationMessageLoading: false })
        })
    })

    describe('team data synchronization', () => {
        it('updates form when team data changes', async () => {
            // Start with empty message
            await expectLogic(logic).toMatchValues({
                confirmationMessageForm: { message: '' },
            })

            // Simulate team update with new message
            const updatedTeam = {
                ...MOCK_DEFAULT_TEAM,
                feature_flag_confirmation_message: 'Updated message from elsewhere',
            }

            teamLogic.actions.updateCurrentTeamSuccess(updatedTeam)

            await expectLogic(logic).toMatchValues({
                confirmationMessageForm: { message: 'Updated message from elsewhere' },
            })
        })

        it('handles undefined team message gracefully', async () => {
            const teamWithUndefinedMessage = {
                ...MOCK_DEFAULT_TEAM,
                feature_flag_confirmation_message: undefined,
            }

            teamLogic.actions.loadCurrentTeamSuccess(teamWithUndefinedMessage)

            await expectLogic(logic).toMatchValues({
                confirmationMessageForm: { message: '' },
            })
        })
    })

    describe('loading states', () => {
        it('tracks submission loading state correctly', async () => {
            // Initial state
            await expectLogic(logic).toMatchValues({ confirmationMessageLoading: false })

            logic.actions.setConfirmationMessageFormValue('message', 'Test message')

            await expectLogic(logic, () => {
                logic.actions.submitConfirmationMessageForm()
            })
                .toDispatchActions(['updateConfirmationMessage'])
                .toMatchValues({ confirmationMessageLoading: true })
                .toDispatchActions(['updateConfirmationMessageSuccess'])
                .toMatchValues({ confirmationMessageLoading: false })
        })
    })
})
