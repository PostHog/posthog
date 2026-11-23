import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'

import { platformAlertsList, platformAlertsPartialUpdate, platformAlertsSnoozeCreate } from './generated/api'
import { PlatformAlertApi, PlatformAlertConfigurationApi } from './generated/api.schemas'
import { platformAlertsLogic } from './platformAlertsLogic'

jest.mock('posthog-js')
jest.mock('./generated/api', () => ({
    platformAlertsList: jest.fn(),
    platformAlertsPartialUpdate: jest.fn(),
    platformAlertsSnoozeCreate: jest.fn(),
}))
jest.mock('@posthog/lemon-ui', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

const mockList = platformAlertsList as jest.MockedFunction<typeof platformAlertsList>
const mockPartialUpdate = platformAlertsPartialUpdate as jest.MockedFunction<typeof platformAlertsPartialUpdate>
const mockSnooze = platformAlertsSnoozeCreate as jest.MockedFunction<typeof platformAlertsSnoozeCreate>

const GROUP = { id: 'group-1', grouping_key: 'checkout', snooze_until: null } as PlatformAlertApi
const CONFIGURATION = {
    id: 'configuration-1',
    name: 'Errors per service',
    snooze_until: null,
    alerts: [GROUP],
} as unknown as PlatformAlertConfigurationApi

function page(results: PlatformAlertConfigurationApi[]): Awaited<ReturnType<typeof platformAlertsList>> {
    return { count: results.length, next: null, previous: null, results }
}

const RELOADED_PAGE = page([{ ...CONFIGURATION, id: 'configuration-reloaded' }])

const ALERT = {
    id: 'alert-1',
    name: 'Slow checkout',
    enabled: true,
    source_kind: 'logs',
    alerts: [],
} as unknown as PlatformAlertConfigurationApi

describe('platformAlertsLogic', () => {
    let logic: ReturnType<typeof platformAlertsLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.clearAllMocks()
        mockList.mockResolvedValue(page([CONFIGURATION]))
        logic = platformAlertsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        mockList.mockResolvedValue(RELOADED_PAGE)
        jest.useFakeTimers()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    test.each<[string, (inAMinute: string) => PlatformAlertConfigurationApi]>([
        ['an alert-wide snooze', (inAMinute) => ({ ...CONFIGURATION, snooze_until: inAMinute })],
        ['a group snooze', (inAMinute) => ({ ...CONFIGURATION, alerts: [{ ...GROUP, snooze_until: inAMinute }] })],
    ])('reloads the list when %s ends, so its mute marker goes', async (_, snoozed) => {
        const inAMinute = dayjs().add(1, 'minute').toISOString()
        const later = dayjs().add(1, 'day').toISOString()
        const snoozedPage = page([snoozed(inAMinute), { ...CONFIGURATION, id: 'configuration-2', snooze_until: later }])
        logic.actions.loadConfigurationsSuccess(snoozedPage)

        jest.advanceTimersByTime(59_000)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.configurationsPage).toEqual(snoozedPage)

        jest.advanceTimersByTime(2_000)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.configurationsPage).toEqual(RELOADED_PAGE)
    })

    it('waits out a snooze longer than the timer limit before it reloads', async () => {
        const inThirtyDays = dayjs().add(30, 'day')
        const snoozedPage = page([{ ...CONFIGURATION, snooze_until: inThirtyDays.toISOString() }])
        logic.actions.loadConfigurationsSuccess(snoozedPage)

        jest.advanceTimersByTime(inThirtyDays.diff(dayjs()) - 1_000)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.configurationsPage).toEqual(snoozedPage)

        jest.advanceTimersByTime(2_000)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.configurationsPage).toEqual(RELOADED_PAGE)
    })

    it('arms no reload when no snooze is active', async () => {
        const endedPage = page([{ ...CONFIGURATION, snooze_until: dayjs().subtract(1, 'minute').toISOString() }])
        logic.actions.loadConfigurationsSuccess(endedPage)

        jest.advanceTimersByTime(24 * 60 * 60 * 1000)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.configurationsPage).toEqual(endedPage)
    })
})

describe('platformAlertsLogic', () => {
    let logic: ReturnType<typeof platformAlertsLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.clearAllMocks()
        mockList.mockResolvedValue({ results: [ALERT], count: 1 } as Awaited<ReturnType<typeof platformAlertsList>>)
        mockPartialUpdate.mockResolvedValue(ALERT)
        mockSnooze.mockResolvedValue(ALERT)
        logic = platformAlertsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        mockList.mockClear()
    })

    it('snoozes the alert for the given hours and reloads the list', async () => {
        const before = Date.now()
        logic.actions.snoozeAlert(ALERT, 4)
        await expectLogic(logic).toFinishAllListeners()

        const [, id, body] = mockSnooze.mock.calls[0]
        expect(id).toEqual(ALERT.id)
        const snoozedFor = new Date(body.snooze_until as string).getTime() - before
        expect(snoozedFor).toBeGreaterThanOrEqual(4 * 3600 * 1000)
        expect(snoozedFor).toBeLessThan(4 * 3600 * 1000 + 60 * 1000)
        expect(mockList).toHaveBeenCalledTimes(1)
    })

    it('unsnoozes the alert with a null snooze', async () => {
        logic.actions.unsnoozeAlert(ALERT)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSnooze).toHaveBeenCalledWith(expect.any(String), ALERT.id, { snooze_until: null })
        expect(mockList).toHaveBeenCalledTimes(1)
    })

    it('keeps a row marked as updating while a second row settles, and skips the reload on failure', async () => {
        let rejectUpdate: (error: Error) => void = () => {}
        mockPartialUpdate.mockReturnValue(new Promise((_, reject) => (rejectUpdate = reject)))
        let resolveSnooze: (alert: PlatformAlertConfigurationApi) => void = () => {}
        mockSnooze.mockReturnValue(new Promise((resolve) => (resolveSnooze = resolve)))

        logic.actions.setAlertEnabled(ALERT, false)
        logic.actions.unsnoozeAlert({ ...ALERT, id: 'alert-2' })
        expect(logic.values.updatingAlertIds).toEqual(new Set([ALERT.id, 'alert-2']))
        expect(mockPartialUpdate).toHaveBeenCalledWith(expect.any(String), ALERT.id, {
            source_kind: 'logs',
            enabled: false,
        })

        rejectUpdate(new Error('boom'))
        await expectLogic(logic).toDispatchActions([logic.actionCreators.setUpdatingAlertId(ALERT.id, false)])
        expect(logic.values.updatingAlertIds).toEqual(new Set(['alert-2']))
        expect(mockList).not.toHaveBeenCalled()

        resolveSnooze(ALERT)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.updatingAlertIds).toEqual(new Set())
        expect(mockList).toHaveBeenCalledTimes(1)
    })
})
