import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AccountsEvents } from 'products/customer_analytics/frontend/components/Accounts/constants'
import type { UserCustomerAnalyticsConfigApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { taskDigestLogic } from './taskDigestLogic'

const CONFIG_URL = '/api/projects/:team_id/user_customer_analytics_config/@me/'

const PINNED_PROPERTIES = [{ kind: 'custom_property' as const, id: 'custom-1' }]

const buildConfig = (overrides: Partial<UserCustomerAnalyticsConfigApi> = {}): UserCustomerAnalyticsConfigApi =>
    ({
        pinned_properties: PINNED_PROPERTIES,
        task_digest: { enabled: false, send_time: '09:00', cadence: 'weekdays' },
        ...overrides,
    }) as UserCustomerAnalyticsConfigApi

describe('taskDigestLogic', () => {
    let logic: ReturnType<typeof taskDigestLogic.build>

    const mountLogic = async (): Promise<void> => {
        logic = taskDigestLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadConfigSuccess']).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        resumeKeaLoadersErrors()
        jest.restoreAllMocks()
    })

    it.each(['settings', 'tasks'] as const)(
        'saves only digest preferences and tracks the %s source',
        async (source) => {
            let submittedBody: unknown
            useMocks({
                get: { [CONFIG_URL]: buildConfig() },
                patch: {
                    [CONFIG_URL]: async ({ request }) => {
                        submittedBody = await request.json()
                        return buildConfig({ task_digest: { enabled: true, send_time: '07:30', cadence: 'every_day' } })
                    },
                },
            })
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            await mountLogic()

            expect(logic.values.draft).toEqual({ enabled: false, send_time: '09:00', cadence: 'weekdays' })
            expect(logic.values.hasChanges).toBe(false)
            logic.actions.setDraft({ send_time: '' })
            expect(logic.values.validSendTime).toBe(false)

            logic.actions.setDraft({ enabled: true, send_time: '07:30', cadence: 'every_day' })
            expect(logic.values.hasChanges).toBe(true)
            expect(logic.values.validSendTime).toBe(true)

            logic.actions.saveTaskDigest({ source })
            await expectLogic(logic).toDispatchActions(['saveTaskDigestSuccess']).toFinishAllListeners()

            expect(submittedBody).toEqual({ task_digest: { enabled: true, send_time: '07:30', cadence: 'every_day' } })
            expect(logic.values.config?.pinned_properties).toEqual(PINNED_PROPERTIES)
            expect(logic.values.hasChanges).toBe(false)
            expect(captureSpy).toHaveBeenCalledWith(
                AccountsEvents.TaskDigestPreferencesSaved,
                expect.objectContaining({ source, enabled: true, send_time: '07:30', cadence: 'every_day' })
            )
        }
    )

    it('keeps the edits and notifies once when the save fails', async () => {
        silenceKeaLoadersErrors()
        const toastSpy = jest.spyOn(lemonToast, 'error')
        useMocks({
            get: { [CONFIG_URL]: buildConfig() },
            patch: { [CONFIG_URL]: () => [500, { detail: 'Could not save the preferences.' }] },
        })
        await mountLogic()

        logic.actions.setDraft({ enabled: true })
        logic.actions.saveTaskDigest()
        await expectLogic(logic).toDispatchActions(['saveTaskDigestFailure']).toFinishAllListeners()

        expect(logic.values.draft.enabled).toBe(true)
        expect(logic.values.hasChanges).toBe(true)
        expect(toastSpy).toHaveBeenCalledTimes(1)
        expect(toastSpy).toHaveBeenCalledWith(expect.stringContaining('Could not save the preferences.'))
    })

    it('reports a failed load instead of showing the defaults as saved preferences', async () => {
        silenceKeaLoadersErrors()
        useMocks({ get: { [CONFIG_URL]: () => [500, { detail: 'Could not load the preferences.' }] } })
        logic = taskDigestLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadConfigFailure']).toFinishAllListeners()

        expect(logic.values.configLoadFailed).toBe(true)
        expect(logic.values.isInitialLoading).toBe(false)
    })
})
