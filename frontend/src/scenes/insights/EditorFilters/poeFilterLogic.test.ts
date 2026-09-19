import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { HogQLQueryModifiers } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightShortId } from '~/types'

import { insightDataLogic } from '../insightDataLogic'
import { insightVizDataLogic } from '../insightVizDataLogic'
import { poeFilterLogic } from './poeFilterLogic'

const Insight123 = '123' as InsightShortId

describe('poeFilterLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': { results: [{}] },
            },
        })
    })

    const setup = (
        teamModifiers: HogQLQueryModifiers,
        defaultModifiers: HogQLQueryModifiers = { personsOnEventsMode: 'person_id_override_properties_joined' }
    ): {
        logic: ReturnType<typeof poeFilterLogic.build>
        vizLogic: ReturnType<typeof insightVizDataLogic.build>
    } => {
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            modifiers: teamModifiers,
            default_modifiers: defaultModifiers,
        })
        featureFlagLogic().mount()

        const props = { dashboardItemId: Insight123 }
        insightDataLogic(props).mount()
        const vizLogic = insightVizDataLogic(props)
        vizLogic.mount()
        const logic = poeFilterLogic(props)
        logic.mount()
        return { logic, vizLogic }
    }

    it.each([
        ['project override is query time', { personsOnEventsMode: 'person_id_override_properties_joined' }, true],
        ['project override is event time', { personsOnEventsMode: 'person_id_override_properties_on_events' }, false],
        ['project override is the deprecated query-time alias', { personsOnEventsMode: 'disabled' }, true],
        ['no project override, so the flag-based default applies', {}, true],
    ] as [string, HogQLQueryModifiers, boolean][])(
        'reads the mode the query will use when %s',
        (_name, teamModifiers, expected) => {
            const { logic } = setup(teamModifiers)
            expect(logic.values.queryTimePoeEnabled).toBe(expected)
        }
    )

    it('lets the insight opt out of a query-time project default', () => {
        const { logic, vizLogic } = setup({ personsOnEventsMode: 'person_id_override_properties_joined' })

        logic.actions.setQueryTimePoeEnabled(false)

        expect(vizLogic.values.querySource?.modifiers?.personsOnEventsMode).toBe(
            'person_id_override_properties_on_events'
        )
        expect(logic.values.queryTimePoeEnabled).toBe(false)
    })

    it('clears the modifier when the project default is already event time', () => {
        const { logic, vizLogic } = setup({ personsOnEventsMode: 'person_id_override_properties_on_events' })

        logic.actions.setQueryTimePoeEnabled(true)
        logic.actions.setQueryTimePoeEnabled(false)

        expect(vizLogic.values.querySource?.modifiers?.personsOnEventsMode).toBeUndefined()
        expect(logic.values.queryTimePoeEnabled).toBe(false)
    })

    it('keeps other insight modifiers when the switch changes', () => {
        const { logic, vizLogic } = setup({ personsOnEventsMode: 'person_id_override_properties_on_events' })
        vizLogic.actions.updateQuerySource({ modifiers: { inCohortVia: 'subquery' } })

        logic.actions.setQueryTimePoeEnabled(true)

        expect(vizLogic.values.querySource?.modifiers).toEqual({
            inCohortVia: 'subquery',
            personsOnEventsMode: 'person_id_override_properties_joined',
        })
    })
})
