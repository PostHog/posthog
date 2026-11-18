import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'

import { initKeaTests } from '~/test/init'

import { TodayMonitorRecent } from './todayMonitor'
import { TodayPeopleRecent } from './todayPeople'
import { TODAY_RECENTS_LIMIT, TODAY_RECENT_KEY, TodayRecent, addTodayRecent } from './todayRecents'
import { todayRecentsLogic } from './todayRecentsLogic'

// The real logic loads every scene. This one lets a test set the active scene logic's record.
jest.mock('scenes/sceneLogic', () => {
    const { actions, kea, path, reducers } = jest.requireActual('kea')
    return {
        sceneLogic: kea([
            path(['test', 'sceneLogic']),
            actions({
                setActiveSceneLogic: (logic: unknown) => ({ logic }),
                setActiveLoadedScene: (scene: unknown) => ({ scene }),
            }),
            reducers({
                activeSceneLogic: [null, { setActiveSceneLogic: (_: unknown, { logic }: { logic: unknown }) => logic }],
                activeLoadedScene: [
                    null,
                    { setActiveLoadedScene: (_: unknown, { scene }: { scene: unknown }) => scene },
                ],
            }),
        ]),
    }
})

const recent = (href: string, name: string = href): TodayPeopleRecent => ({ type: 'cohort', name, href })
const issue: TodayMonitorRecent = { type: 'error_tracking_issue', name: 'Checkout timeout', href: '/error-tracking/1' }
const sceneShowing = (record: TodayRecent | null): unknown => ({
    selectors: { [TODAY_RECENT_KEY]: () => record },
})

describe('todayRecentsLogic', () => {
    it('puts a visit first, renames it in place, and keeps the list at the limit', () => {
        const a = recent('/a')
        const b = recent('/b')
        expect(addTodayRecent([a, b], b).map((item) => item.href)).toEqual(['/b', '/a'])
        expect(addTodayRecent([a, b], { ...a, name: 'Renamed' })).toEqual([{ ...a, name: 'Renamed' }, b])

        const unchanged = [a, b]
        expect(addTodayRecent(unchanged, a)).toBe(unchanged)

        const full = Array.from({ length: TODAY_RECENTS_LIMIT }, (_, index) => recent(`/${index}`))
        const added = addTodayRecent(full, recent('/new'))
        expect(added).toHaveLength(TODAY_RECENTS_LIMIT)
        expect(added[0].href).toBe('/new')
    })

    test.each([
        [
            'a cohort with today-rail-nav on',
            { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true },
            recent('/cohorts/5', 'Churned'),
            ['Churned'],
            [],
        ],
        ['a cohort with today-rail-nav off', {}, recent('/cohorts/5', 'Churned'), [], []],
        [
            'an issue with monitor-area on',
            { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true, [FEATURE_FLAGS.MONITOR_AREA]: true },
            issue,
            [],
            ['Checkout timeout'],
        ],
        ['an issue with monitor-area off', { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true }, issue, [], []],
    ])('a scene showing %s adds it to its pane once it loads', (_, flags, record, people, monitor) => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(Object.keys(flags), flags)
        sceneLogic.mount()
        const logic = todayRecentsLogic()
        logic.mount()
        const setActive = (sceneLogic.actions as any).setActiveSceneLogic

        setActive(sceneShowing(null))
        expect(logic.values.peopleRecents).toEqual([])

        setActive(sceneShowing(record))
        expect(logic.values.peopleRecents.map((item) => item.name)).toEqual(people)
        expect(logic.values.monitorRecents.map((item) => item.name)).toEqual(monitor)
    })

    it('reads the record with the props of the open scene', () => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: true,
        })
        sceneLogic.mount()
        const logic = todayRecentsLogic()
        logic.mount()
        const sceneActions = sceneLogic.actions as any

        // Like the cohort and group scene logics, the selector reads the record id from its props.
        sceneActions.setActiveLoadedScene({
            sceneParams: { params: { id: '7' } },
            paramsToProps: ({ params }: { params: { id: string } }) => ({ id: params.id }),
        })
        sceneActions.setActiveSceneLogic({
            selectors: {
                [TODAY_RECENT_KEY]: (_: unknown, props: { id?: string }) =>
                    props.id ? recent(`/cohorts/${props.id}`, `Cohort ${props.id}`) : null,
            },
        })

        expect(logic.values.peopleRecents).toEqual([recent('/cohorts/7', 'Cohort 7')])
    })

    it('stores a recent, newest first, and lists the rows by name', () => {
        initKeaTests()
        const logic = todayRecentsLogic()
        logic.mount()

        logic.actions.addRecent(recent('/cohorts/1'))
        logic.actions.addRecent(recent('/cohorts/2'))

        expect(logic.values.peopleRecents.map((item) => item.href)).toEqual(['/cohorts/2', '/cohorts/1'])
        expect(logic.values.peopleRecentRows.map((item) => item.href)).toEqual(['/cohorts/1', '/cohorts/2'])
    })
})
