import { expectLogic } from 'kea-test-utils'
import { defaultAPIMocks, mockAPI } from 'lib/api.mock'
import { List } from 'react-virtualized/dist/commonjs/List'
import { initKeaTestLogic } from '~/test/init'
import {
    DEFAULT_SCROLLING_RESET_TIME_INTERVAL,
    eventsListLogic,
} from 'scenes/session-recordings/player/eventsListLogic'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

jest.mock('lib/api')

describe('eventsListLogic', () => {
    let logic: ReturnType<typeof eventsListLogic.build>

    mockAPI(async (url) => {
        return defaultAPIMocks(url)
    })

    initKeaTestLogic({
        logic: eventsListLogic,
        onLogic: (l) => (logic = l),
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([sessionRecordingLogic, sessionRecordingPlayerLogic, eventUsageLogic])
        })
    })

    describe('setLocalFilter', () => {
        it('calls setFilter in parent logic with debounce', async () => {
            const filters = { query: 'mini pretzels' }
            await expectLogic(logic, () => {
                logic.actions.setLocalFilters({ query: 'no mini pretzels' })
                logic.actions.setLocalFilters(filters)
            })
                .toNotHaveDispatchedActions([
                    sessionRecordingLogic.actionCreators.setFilters({ query: 'no mini pretzels' }),
                ])
                .toDispatchActions([sessionRecordingLogic.actionCreators.setFilters(filters)])
        })
    })

    describe('handle event click', () => {
        it('happy case', async () => {
            await expectLogic(logic, () => {
                logic.actions.handleEventClick(10)
            }).toDispatchActions(['handleEventClick', sessionRecordingPlayerLogic.actionCreators.seek(10)])
        })

        const nanInputs: Record<string, any> = {
            null: null,
            undefined: undefined,
            '00:00:00': '00:00:00',
            '2021-11-18T21:03:48.305000Z': '2021-11-18T21:03:48.305000Z',
        }

        Object.entries(nanInputs).forEach(([key, value]) => {
            it(`NaN case: ${key}`, async () => {
                await expectLogic(logic, async () => {
                    logic.actions.handleEventClick(value)
                })
                    .toDispatchActions(['handleEventClick'])
                    .toNotHaveDispatchedActions([sessionRecordingPlayerLogic.actionCreators.seek(value)])
            })
        })
    })

    describe('current position finder', () => {
        it('disable position finder from showing with debounce on scroll to', async () => {
            await expectLogic(logic, () => {
                logic.actions.scrollTo()
                logic.actions.scrollTo()
            })
                .toDispatchActions(['scrollTo', 'scrollTo', 'enablePositionFinder'])
                .toNotHaveDispatchedActions(['scrollTo', 'enablePositionFinder'])
                .toMatchValues({
                    shouldHidePositionFinder: false,
                })
        })
        it('disable position finder from showing with delay on scroll to', async () => {
            await expectLogic(logic, () => {
                logic.actions.scrollTo()
            })
                .toDispatchActions(['scrollTo'])
                .toMatchValues({
                    shouldHidePositionFinder: true,
                })
                .delay(DEFAULT_SCROLLING_RESET_TIME_INTERVAL / 4) // still hidden
                .toMatchValues({
                    shouldHidePositionFinder: true,
                })
                .delay(DEFAULT_SCROLLING_RESET_TIME_INTERVAL + 100) // buffer time
                .toDispatchActions(['enablePositionFinder'])
                .toMatchValues({
                    shouldHidePositionFinder: false,
                })
        })
        it('scroll to specific rowIndex', async () => {
            const mockedList = {
                scrollToPosition: jest.fn(),
                getOffsetForRow: jest.fn(({}: { alignment: string; index: number }) => 40),
            }

            await expectLogic(logic, async () => {
                logic.actions.setList(mockedList as unknown as List)
                logic.actions.scrollTo(10)
            }).toDispatchActions([eventUsageLogic.actionCreators.reportRecordingScrollTo(10)])

            expect(mockedList.getOffsetForRow.mock.calls.length).toBe(1)
            expect(mockedList.getOffsetForRow.mock.calls[0][0]).toEqual({ alignment: 'center', index: 10 })
            expect(mockedList.scrollToPosition.mock.calls.length).toBe(1)
            expect(mockedList.scrollToPosition.mock.calls[0][0]).toEqual(40)
        })
    })
})
