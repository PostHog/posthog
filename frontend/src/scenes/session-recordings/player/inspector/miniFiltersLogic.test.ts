import { expectLogic } from 'kea-test-utils'

import {
    SharedListMiniFilter,
    isMiniFilterGroupFullyEnabled,
    miniFiltersLogic,
} from 'scenes/session-recordings/player/inspector/miniFiltersLogic'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'

import { initKeaTests } from '~/test/init'

describe('miniFiltersLogic', () => {
    let logic: ReturnType<typeof miniFiltersLogic.build>
    let eventLogic: ReturnType<typeof sessionRecordingEventUsageLogic.build>

    beforeEach(() => {
        initKeaTests()
        eventLogic = sessionRecordingEventUsageLogic()
        eventLogic.mount()
        logic = miniFiltersLogic()
        logic.mount()
    })
    describe('initialState', () => {
        it('sets default values', () => {
            expectLogic(logic).toMatchValues({
                showOnlyMatching: false,
                selectedMiniFilters: [
                    'events-posthog',
                    'events-custom',
                    'events-pageview',
                    'events-autocapture',
                    'events-exceptions',
                    'console-info',
                    'console-warn',
                    'console-error',
                    'comment',
                    'logs-info',
                    'logs-warn',
                    'logs-error',
                ],
            })
        })
    })

    describe('setShowOnlyMatching', () => {
        it('start as false', async () => {
            await expectLogic(logic).toMatchValues({
                showOnlyMatching: false,
            })
        })
        it('happy case', async () => {
            await expectLogic(logic, () => {
                logic.actions.setShowOnlyMatching(true)
            })
                .toDispatchActions(['setShowOnlyMatching'])
                .toMatchValues({
                    showOnlyMatching: true,
                })
        })
    })

    describe('miniFilters', () => {
        afterEach(() => {
            localStorage.clear()
        })

        it('can unselect', async () => {
            await expectLogic(logic, () => {
                logic.actions.setMiniFilter('events-posthog', false)
            }).toMatchValues({
                selectedMiniFilters: [
                    'events-custom',
                    'events-pageview',
                    'events-autocapture',
                    'events-exceptions',
                    'console-info',
                    'console-warn',
                    'console-error',
                    'comment',
                    'logs-info',
                    'logs-warn',
                    'logs-error',
                ],
            })
        })
    })

    describe('setMiniFilters reporting', () => {
        it('reports each affected key, including on disable', async () => {
            await expectLogic(logic, () => {
                logic.actions.setMiniFilters(['console-info', 'console-app-state'], false)
            }).toDispatchActions([
                eventLogic.actionCreators.reportRecordingInspectorMiniFilterViewed('console-info', false),
                eventLogic.actionCreators.reportRecordingInspectorMiniFilterViewed('console-app-state', false),
            ])
        })
    })

    describe('isMiniFilterGroupFullyEnabled', () => {
        const asFilters = (enabledFlags: boolean[]): SharedListMiniFilter[] =>
            enabledFlags.map((enabled, i) => ({ type: 'console', key: `k${i}`, name: `k${i}`, enabled }))

        it.each([
            { enabledFlags: [true, true, true], expected: true },
            { enabledFlags: [true, false, true], expected: false },
            { enabledFlags: [false, false, false], expected: false },
            { enabledFlags: [], expected: true },
        ])('returns $expected for $enabledFlags', ({ enabledFlags, expected }) => {
            expect(isMiniFilterGroupFullyEnabled(asFilters(enabledFlags))).toEqual(expected)
        })
    })
})
