import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { createHogFunction } from '../_tests/fixtures'
import { HogFlow } from '../schema/hogflow'
import { HogFunctionFilters } from '../types'
import { buildEventNameGate } from './event-name-gate'

const named = (...ids: (string | null)[]) => ids.map((id) => ({ id, type: 'events' as const }))

const flowTriggeredBy = (trigger: HogFlow['trigger']): HogFlow =>
    new FixtureHogFlowBuilder().withSimpleWorkflow({ trigger }).build()

describe('buildEventNameGate', () => {
    it.each<[string, HogFunctionFilters | null, string, boolean]>([
        ['an event the filter names', { events: named('$pageview', 'signed_up') }, 'signed_up', true],
        ['an event the filter does not name', { events: named('$pageview') }, 'signed_up', false],
        [
            'any event when the filter also matches actions',
            { events: named('$pageview'), actions: [{ id: '1', type: 'actions' }] },
            'signed_up',
            true,
        ],
        ['any event when the filter lists all events', { events: named('$pageview', null) }, 'signed_up', true],
        ['any event when the filter names no event', { events: [], bytecode: ['_h', 29] }, 'signed_up', true],
        ['any event when the function has no filters', null, 'signed_up', true],
        [
            'no event for a function that runs on another source',
            { source: 'person-updates', events: [] },
            'signed_up',
            false,
        ],
    ])('a destination admits %s', (_, filters, eventName, admitted) => {
        const gate = buildEventNameGate({
            hogFunctions: [createHogFunction({ filters })],
            hogFlows: [],
            alsoAdmitted: [],
        })

        expect(gate.admits(eventName)).toBe(admitted)
    })

    it.each<[string, HogFlow['trigger'], string, boolean]>([
        ['an event its trigger names', { type: 'event', filters: { events: named('signed_up') } }, 'signed_up', true],
        ['no other event', { type: 'event', filters: { events: named('signed_up') } }, '$pageview', false],
        ['no event when it is not triggered by events', { type: 'schedule' }, '$pageview', false],
    ])('a workflow admits %s', (_, trigger, eventName, admitted) => {
        const gate = buildEventNameGate({ hogFunctions: [], hogFlows: [flowTriggeredBy(trigger)], alsoAdmitted: [] })

        expect(gate.admits(eventName)).toBe(admitted)
    })

    it('admits the events the caller reads for itself', () => {
        const gate = buildEventNameGate({
            hogFunctions: [createHogFunction({ filters: { events: named('$pageview') } })],
            hogFlows: [],
            alsoAdmitted: ['$push_notification_opened'],
        })

        expect(gate.admits('$push_notification_opened')).toBe(true)
    })

    it('records filtered for each destination and workflow the event would have been filtered by', () => {
        const destination = createHogFunction({ team_id: 7, filters: { events: named('$pageview') } })
        const otherSource = createHogFunction({ team_id: 7, filters: { source: 'person-updates' } })
        const workflow = { ...flowTriggeredBy({ type: 'event', filters: { events: named('signed_up') } }), team_id: 7 }
        const scheduled = flowTriggeredBy({ type: 'schedule' })

        const gate = buildEventNameGate({
            hogFunctions: [destination, otherSource],
            hogFlows: [workflow, scheduled],
            alsoAdmitted: [],
        })

        expect(gate.filteredMetrics()).toEqual({
            hogFunctions: [
                { team_id: 7, app_source_id: destination.id, metric_kind: 'other', metric_name: 'filtered', count: 1 },
            ],
            hogFlows: [
                {
                    team_id: 7,
                    app_source_id: workflow.id,
                    metric_kind: 'other',
                    metric_name: 'filtered',
                    count: 1,
                    app_source_version: { id: workflow.id, version: workflow.version },
                },
            ],
        })
    })
})
