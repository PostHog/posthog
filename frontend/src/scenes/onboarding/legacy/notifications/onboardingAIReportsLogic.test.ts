import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'

import { subscriptionsCreate, subscriptionsPartialUpdate } from 'products/subscriptions/frontend/generated/api'

import { onboardingAIReportsLogic } from './onboardingAIReportsLogic'

jest.mock('products/subscriptions/frontend/generated/api', () => ({
    subscriptionsCreate: jest.fn(),
    subscriptionsPartialUpdate: jest.fn(),
}))

const mockedCreate = jest.mocked(subscriptionsCreate)
const mockedPartialUpdate = jest.mocked(subscriptionsPartialUpdate)

describe('onboardingAIReportsLogic', () => {
    let logic: ReturnType<typeof onboardingAIReportsLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockedCreate.mockReset().mockResolvedValue({ id: 123 } as any)
        mockedPartialUpdate.mockReset().mockResolvedValue({ id: 123 } as any)
        jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast-id')

        logic = onboardingAIReportsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    // Catches payload drift the backend would reject at runtime (dropping `interval`), and
    // `send_test_now` flipping back to its server default of true, which would immediately
    // mail an AI report over a project that likely has no events yet.
    it('creates a weekly email subscription with a start date about a week out', async () => {
        await expectLogic(logic, () => logic.actions.createReportSubscription()).toFinishAllListeners()

        expect(mockedCreate).toHaveBeenCalledTimes(1)
        const [, payload] = mockedCreate.mock.calls[0]
        expect(payload).toMatchObject({
            target_type: 'email',
            frequency: 'weekly',
            interval: 1,
            send_test_now: false,
        })
        expect(payload.prompt).toBeTruthy()
        expect(payload.title).toBeTruthy()
        const daysOut = dayjs(payload.start_date).diff(dayjs(), 'day', true)
        expect(daysOut).toBeGreaterThan(6)
        expect(daysOut).toBeLessThan(8)
        expect(logic.values.createdSubscriptionId).toBe(123)
    })

    it('does not create a second subscription while one exists', async () => {
        await expectLogic(logic, () => logic.actions.createReportSubscription()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.createReportSubscription()).toFinishAllListeners()

        expect(mockedCreate).toHaveBeenCalledTimes(1)
    })

    // The error leg of the double-submit guard: a failed create must leave the button usable
    // (loading reset, no phantom created state) and tell the user where to recover.
    it('resets state and shows a toast when creation fails', async () => {
        mockedCreate.mockRejectedValue(new Error('quota'))

        await expectLogic(logic, () => logic.actions.createReportSubscription()).toFinishAllListeners()

        expect(logic.values.createdSubscriptionId).toBeNull()
        expect(logic.values.createdSubscriptionIdLoading).toBe(false)
        expect(lemonToast.error).toHaveBeenCalled()
    })

    it('undo soft-deletes the created subscription and clears the created state', async () => {
        await expectLogic(logic, () => logic.actions.createReportSubscription()).toFinishAllListeners()

        await expectLogic(logic, () => logic.actions.removeReportSubscription()).toFinishAllListeners()

        expect(mockedPartialUpdate).toHaveBeenCalledTimes(1)
        const [, id, payload] = mockedPartialUpdate.mock.calls[0]
        expect(id).toBe(123)
        expect(payload).toEqual({ deleted: true })
        expect(logic.values.createdSubscriptionId).toBeNull()
    })
})
