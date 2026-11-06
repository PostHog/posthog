import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'

import { initKeaTests } from '~/test/init'

import { TODAY_PEOPLE_RECENT_KEY, TodayPeopleRecent } from './todayPeople'
import { TODAY_PEOPLE_RECENTS_LIMIT, addPeopleRecent, todayPeopleRecentsLogic } from './todayPeopleRecentsLogic'

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
const sceneShowing = (record: TodayPeopleRecent | null): unknown => ({
    selectors: { [TODAY_PEOPLE_RECENT_KEY]: () => record },
})

describe('todayPeopleRecentsLogic', () => {
    it('puts a visit first, renames it in place, and keeps the list at the limit', () => {
        const a = recent('/a')
        const b = recent('/b')
        expect(addPeopleRecent([a, b], b).map((item) => item.href)).toEqual(['/b', '/a'])
        expect(addPeopleRecent([a, b], { ...a, name: 'Renamed' })).toEqual([{ ...a, name: 'Renamed' }, b])

        const unchanged = [a, b]
        expect(addPeopleRecent(unchanged, a)).toBe(unchanged)

        const full = Array.from({ length: TODAY_PEOPLE_RECENTS_LIMIT }, (_, index) => recent(`/${index}`))
        const added = addPeopleRecent(full, recent('/new'))
        expect(added).toHaveLength(TODAY_PEOPLE_RECENTS_LIMIT)
        expect(added[0].href).toBe('/new')
    })

    test.each([
        ['on', true, ['Churned']],
        ['off', false, []],
    ])('with today-rail-nav %s, a scene adds %o once its record loads', (_, enabled, names) => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: enabled,
        })
        sceneLogic.mount()
        const logic = todayPeopleRecentsLogic()
        logic.mount()
        const setActive = (sceneLogic.actions as any).setActiveSceneLogic

        setActive(sceneShowing(null))
        expect(logic.values.recents).toEqual([])

        setActive(sceneShowing(recent('/cohorts/5', 'Churned')))
        expect(logic.values.recents.map((item) => item.name)).toEqual(names)
    })

    it('reads the record with the props of the open scene', () => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: true,
        })
        sceneLogic.mount()
        const logic = todayPeopleRecentsLogic()
        logic.mount()
        const sceneActions = sceneLogic.actions as any

        // Like the cohort and group scene logics, the selector reads the record id from its props.
        sceneActions.setActiveLoadedScene({
            sceneParams: { params: { id: '7' } },
            paramsToProps: ({ params }: { params: { id: string } }) => ({ id: params.id }),
        })
        sceneActions.setActiveSceneLogic({
            selectors: {
                [TODAY_PEOPLE_RECENT_KEY]: (_: unknown, props: { id?: string }) =>
                    props.id ? recent(`/cohorts/${props.id}`, `Cohort ${props.id}`) : null,
            },
        })

        expect(logic.values.recents).toEqual([recent('/cohorts/7', 'Cohort 7')])
    })

    it('stores a recent, newest first, and lists the rows by name', () => {
        initKeaTests()
        const logic = todayPeopleRecentsLogic()
        logic.mount()

        logic.actions.addRecent(recent('/cohorts/1'))
        logic.actions.addRecent(recent('/cohorts/2'))

        expect(logic.values.recents.map((item) => item.href)).toEqual(['/cohorts/2', '/cohorts/1'])
        expect(logic.values.recentRows.map((item) => item.href)).toEqual(['/cohorts/1', '/cohorts/2'])
    })
})
