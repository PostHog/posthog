import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import { platformAlertsRetrieve, platformAlertsSnoozeGroupCreate } from './generated/api'
import { PlatformAlertApi, PlatformAlertConfigurationApi } from './generated/api.schemas'
import { platformAlertLogic } from './platformAlertLogic'

jest.mock('posthog-js')
jest.mock('./generated/api', () => ({
    platformAlertsRetrieve: jest.fn(),
    platformAlertsSnoozeGroupCreate: jest.fn(),
}))
jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

const mockRetrieve = platformAlertsRetrieve as jest.MockedFunction<typeof platformAlertsRetrieve>
const mockSnooze = platformAlertsSnoozeGroupCreate as jest.MockedFunction<typeof platformAlertsSnoozeGroupCreate>

const GROUP: PlatformAlertApi = {
    id: 'group-1',
    grouping_key: '{"service_name":"checkout"}',
    state: 'firing',
    firing_started_at: '2026-10-05T11:00:00Z',
    last_notified_at: '2026-10-05T11:00:05Z',
    snooze_until: null,
    labels: { service_name: 'checkout' },
}
const OTHER_GROUP: PlatformAlertApi = { ...GROUP, id: 'group-2', grouping_key: '{"service_name":"api"}' }

const CONFIGURATION: PlatformAlertConfigurationApi = {
    id: 'configuration-1',
    name: 'Errors per service',
    enabled: true,
    source_kind: 'logs',
    source_config: {},
    check_interval_minutes: 1,
    recurrence_unit: null,
    anchor_time: null,
    evaluation_periods: 1,
    datapoints_to_alarm: 1,
    cooldown_minutes: 0,
    schedule_restriction: null,
    next_check_at: null,
    consecutive_failures: 0,
    legacy_configuration_id: null,
    grouping: { mode: 'by_result_labels', keys: ['service_name'], max_instances: 10, on_overflow: 'degrade_visible' },
    snooze_until: null,
    check_status: 'ok',
    overflowed_groups: 0,
    overflow_is_lower_bound: false,
    owner: 'platform',
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    alerts: [GROUP, OTHER_GROUP],
}

describe('platformAlertLogic', () => {
    let logic: ReturnType<typeof platformAlertLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.clearAllMocks()
        mockRetrieve.mockResolvedValue(CONFIGURATION)
        logic = platformAlertLogic({ id: CONFIGURATION.id })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    test.each<[string, Partial<PlatformAlertConfigurationApi>, boolean]>([
        ['platform-owned grouped alert', {}, true],
        ['source-owned alert', { owner: 'source' }, false],
        ['ungrouped alert', { grouping: { mode: 'single', keys: [] } }, false],
    ])('canSnoozeGroups: %s', (_, overrides, expected) => {
        logic.actions.loadConfigurationSuccess({ ...CONFIGURATION, ...overrides })
        expect(logic.values.canSnoozeGroups).toBe(expected)
    })

    test.each<[string, () => string | null, boolean]>([
        ['no alert-wide snooze', () => null, false],
        ['an alert-wide snooze that ended', () => dayjs().subtract(1, 'hour').toISOString(), false],
        ['an active alert-wide snooze', () => dayjs().add(1, 'day').toISOString(), true],
    ])('alertSnoozeUntil: %s', (_, snoozeUntil, active) => {
        const snooze_until = snoozeUntil()
        logic.actions.loadConfigurationSuccess({ ...CONFIGURATION, snooze_until })
        expect(logic.values.alertSnoozeUntil).toBe(active ? snooze_until : null)
    })

    it('reloads when the alert-wide snooze ends, so the group snooze menu comes back', async () => {
        jest.useFakeTimers()
        try {
            mockRetrieve.mockClear()
            logic.actions.loadConfigurationSuccess({
                ...CONFIGURATION,
                snooze_until: dayjs().add(1, 'minute').toISOString(),
            })
            expect(logic.values.alertSnoozeUntil).not.toBeNull()

            jest.advanceTimersByTime(61_000)
            await expectLogic(logic).toFinishAllListeners()

            expect(mockRetrieve).toHaveBeenCalledTimes(1)
            expect(logic.values.alertSnoozeUntil).toBeNull()
        } finally {
            jest.useRealTimers()
        }
    })

    it('snoozes one group, holds the in-flight state until the API answers, and swaps in the returned group', async () => {
        let respond: (alert: PlatformAlertApi) => void = () => {}
        mockSnooze.mockReturnValue(new Promise((resolve) => (respond = resolve)))

        const before = Date.now()
        logic.actions.snoozeGroupFor(GROUP.grouping_key, '4h')
        await expectLogic(logic).toMatchValues({ snoozingGroupKey: GROUP.grouping_key })
        const [, configurationId, body] = mockSnooze.mock.calls[0]
        expect(configurationId).toEqual(CONFIGURATION.id)
        expect(body.grouping_key).toEqual(GROUP.grouping_key)
        const hoursAhead = (Date.parse(body.snooze_until!) - before) / 3_600_000
        expect(hoursAhead).toBeGreaterThanOrEqual(4)
        expect(hoursAhead).toBeLessThan(4.01)

        const snoozed = { ...GROUP, state: 'snoozed' as const, snooze_until: '2026-10-05T16:00:00Z' }
        respond(snoozed)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.snoozingGroupKey).toBeNull()
        expect(logic.values.configuration?.alerts).toEqual([snoozed, OTHER_GROUP])
        expect(posthog.capture).toHaveBeenCalledWith('platform alert group snoozed', {
            configuration_id: CONFIGURATION.id,
            source_kind: 'logs',
            duration: '4h',
        })
    })

    it('clears a snooze with a null time and tracks it as an unsnooze', async () => {
        mockSnooze.mockResolvedValue(GROUP)

        logic.actions.unsnoozeGroup(GROUP.grouping_key)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSnooze).toHaveBeenCalledWith(expect.any(String), CONFIGURATION.id, {
            grouping_key: GROUP.grouping_key,
            snooze_until: null,
        })
        expect(posthog.capture).toHaveBeenCalledWith('platform alert group unsnoozed', {
            configuration_id: CONFIGURATION.id,
            source_kind: 'logs',
            duration: null,
        })
    })

    test.each<[number, boolean]>([
        [409, false],
        [400, false],
        [404, true],
    ])(
        'a %s shows the API message, resets the in-flight state, and reloads only for a missing group',
        async (status, reloads) => {
            mockSnooze.mockRejectedValue({ status, detail: `API says ${status}` })
            mockRetrieve.mockClear()

            logic.actions.snoozeGroupFor(GROUP.grouping_key, '1h')
            await expectLogic(logic).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith(`API says ${status}`)
            expect(logic.values.snoozingGroupKey).toBeNull()
            expect(logic.values.configuration?.alerts).toEqual([GROUP, OTHER_GROUP])
            expect(posthog.capture).not.toHaveBeenCalled()
            expect(mockRetrieve).toHaveBeenCalledTimes(reloads ? 1 : 0)
        }
    )
})
