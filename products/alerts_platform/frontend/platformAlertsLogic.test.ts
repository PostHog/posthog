import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'

import { platformAlertsList } from './generated/api'
import { PlatformAlertApi, PlatformAlertConfigurationApi } from './generated/api.schemas'
import { platformAlertsLogic } from './platformAlertsLogic'

jest.mock('./generated/api', () => ({
    platformAlertsList: jest.fn(),
}))

const mockList = platformAlertsList as jest.MockedFunction<typeof platformAlertsList>

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
