import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { platformAlertsList, platformAlertsPartialUpdate, platformAlertsSnoozeCreate } from './generated/api'
import { PlatformAlertApi, PlatformAlertConfigurationApi } from './generated/api.schemas'
import { platformAlertsLogic } from './platformAlertsLogic'

jest.mock('posthog-js')
jest.mock('./generated/api', () => ({
    platformAlertsList: jest.fn(),
    platformAlertsPartialUpdate: jest.fn(),
    platformAlertsSnoozeCreate: jest.fn(),
    platformAlertsSnoozeGroupCreate: jest.requireActual('./generated/api').platformAlertsSnoozeGroupCreate,
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
        [
            'a group snooze before a later alert-wide snooze',
            (inAMinute) => ({
                ...CONFIGURATION,
                snooze_until: dayjs().add(1, 'hour').toISOString(),
                alerts: [{ ...GROUP, snooze_until: inAMinute }],
            }),
        ],
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
    const SNOOZED = { ...ALERT, id: 'alert-2', snooze_until: dayjs().add(1, 'day').toISOString() }

    let logic: ReturnType<typeof platformAlertsLogic.build>
    let stored: Map<string, PlatformAlertConfigurationApi>

    const save = (id: string, changes: Partial<PlatformAlertConfigurationApi>): PlatformAlertConfigurationApi => {
        const saved = { ...stored.get(id)!, ...changes }
        stored.set(id, saved)
        return saved
    }
    const listed = (id: string): PlatformAlertConfigurationApi | undefined =>
        logic.values.configurationsPage?.results.find((configuration) => configuration.id === id)

    beforeEach(async () => {
        initKeaTests()
        jest.clearAllMocks()
        stored = new Map([
            [ALERT.id, ALERT],
            [SNOOZED.id, SNOOZED],
        ])
        mockList.mockImplementation(async () => page([...stored.values()]))
        mockSnooze.mockImplementation(async (_, id, { snooze_until }) => save(id, { snooze_until }))
        mockPartialUpdate.mockImplementation(async (_, id, changes) => {
            if (!changes?.source_kind) {
                throw { detail: 'source_kind is required' }
            }
            return save(id, changes as Partial<PlatformAlertConfigurationApi>)
        })
        logic = platformAlertsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('snoozes the alert for the given hours and shows it in the reloaded list', async () => {
        const before = Date.now()
        logic.actions.snoozeAlert(ALERT, 4)
        await expectLogic(logic).toFinishAllListeners()

        const snoozedFor = new Date(listed(ALERT.id)?.snooze_until as string).getTime() - before
        expect(snoozedFor).toBeGreaterThanOrEqual(4 * 3600 * 1000)
        expect(snoozedFor).toBeLessThan(4 * 3600 * 1000 + 60 * 1000)
    })

    it.each<[string, () => void, string | null]>([
        ['snoozes', () => logic.actions.snoozeGroup(ALERT, GROUP, '1h', 1), expect.any(String)],
        ['unsnoozes', () => logic.actions.unsnoozeGroup(ALERT, GROUP), null],
    ])('%s one group by its key and reloads the list', async (_, act, snoozeUntil) => {
        const received: unknown[] = []
        useMocks({
            post: {
                [`/api/projects/:team_id/platform_alerts/${ALERT.id}/snooze_group/`]: async ({ request }) => {
                    received.push(await request.json())
                    return GROUP
                },
            },
        })
        const reloaded = { ...ALERT, alerts: [GROUP] }
        mockList.mockResolvedValue({ results: [reloaded], count: 1 } as Awaited<ReturnType<typeof platformAlertsList>>)
        act()
        expect(logic.values.updatingAlertIds).toEqual(new Set([GROUP.id]))
        await expectLogic(logic).toFinishAllListeners()

        expect(received).toEqual([{ grouping_key: GROUP.grouping_key, snooze_until: snoozeUntil }])
        expect(logic.values.configurationsPage?.results).toEqual([reloaded])
    })

    it.each<[number, PlatformAlertConfigurationApi[]]>([
        [404, []],
        [500, [ALERT, SNOOZED]],
    ])('after a group snooze fails with %s, the list is %p', async (status, expected) => {
        useMocks({
            post: { [`/api/projects/:team_id/platform_alerts/${ALERT.id}/snooze_group/`]: [status, {}] },
        })
        mockList.mockResolvedValue({ results: [], count: 0 } as Awaited<ReturnType<typeof platformAlertsList>>)
        logic.actions.snoozeGroup(ALERT, GROUP, '1h', 1)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.configurationsPage?.results).toEqual(expected)
    })

    it('unsnoozes the alert and shows it in the reloaded list', async () => {
        expect(listed(SNOOZED.id)?.snooze_until).toEqual(SNOOZED.snooze_until)

        logic.actions.unsnoozeAlert(SNOOZED)
        await expectLogic(logic).toFinishAllListeners()

        expect(listed(SNOOZED.id)?.snooze_until).toBeNull()
    })

    it('disables the alert and shows it in the reloaded list', async () => {
        logic.actions.setAlertEnabled(ALERT, false)
        await expectLogic(logic).toFinishAllListeners()

        expect(listed(ALERT.id)?.enabled).toBe(false)
    })

    it('keeps a row marked as updating while a second row settles, and skips the reload on failure', async () => {
        let rejectUpdate: (error: Error) => void = () => {}
        mockPartialUpdate.mockReturnValueOnce(new Promise((_, reject) => (rejectUpdate = reject)))
        let releaseSnooze: () => void = () => {}
        const released = new Promise<void>((resolve) => (releaseSnooze = resolve))
        mockSnooze.mockImplementationOnce(async (_, id, { snooze_until }) => {
            await released
            return save(id, { snooze_until })
        })
        const pageBefore = logic.values.configurationsPage

        logic.actions.setAlertEnabled(ALERT, false)
        logic.actions.unsnoozeAlert(SNOOZED)
        expect(logic.values.updatingAlertIds).toEqual(new Set([ALERT.id, SNOOZED.id]))

        rejectUpdate(new Error('boom'))
        await expectLogic(logic).toDispatchActions([logic.actionCreators.setUpdatingAlertId(ALERT.id, false)])
        expect(logic.values.updatingAlertIds).toEqual(new Set([SNOOZED.id]))
        expect(logic.values.configurationsPageLoading).toBe(false)
        expect(logic.values.configurationsPage).toBe(pageBefore)

        releaseSnooze()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.updatingAlertIds).toEqual(new Set())
        expect(listed(SNOOZED.id)?.snooze_until).toBeNull()
        expect(listed(ALERT.id)?.enabled).toBe(true)
    })
})
