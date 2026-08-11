import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'
import { PluginEvent } from '~/plugin-scaffold'
import { Team } from '~/types'

import { PersonContext } from './person-context'
import { PersonMergeService } from './person-merge-service'

describe('PersonMergeService.handleIdentifyOrAlias', () => {
    const teamId = 2

    let queueMessages: jest.Mock

    function serviceFor(event: string, properties: Record<string, unknown>, distinctId = 'user-1'): PersonMergeService {
        queueMessages = jest.fn().mockResolvedValue(undefined)
        const context = {
            event: { event, distinct_id: distinctId, uuid: 'event-uuid-1', properties } as unknown as PluginEvent,
            eventProperties: properties,
            team: { id: teamId } as Team,
            distinctId,
            timestamp: DateTime.utc(2026, 1, 1),
            outputs: { queueMessages },
            mergeFoldPlan: undefined,
        } as unknown as PersonContext
        return new PersonMergeService(context)
    }

    function emittedWarning(): { type: string; details: Record<string, unknown> } | undefined {
        if (queueMessages.mock.calls.length === 0) {
            return undefined
        }
        const [, messages] = queueMessages.mock.calls[0]
        const serialized = parseJSON(messages[0].value.toString()) as { type: string; details: string }
        return { type: serialized.type, details: parseJSON(serialized.details) }
    }

    it('warns when $identify carries no $anon_distinct_id', async () => {
        await serviceFor('$identify', { $set: { plan: 'pro' } }).handleIdentifyOrAlias()

        expect(emittedWarning()).toEqual({
            type: 'identify_missing_anon_distinct_id',
            details: expect.objectContaining({
                distinctId: 'user-1',
                eventUuid: 'event-uuid-1',
                category: 'merge',
                severity: 'warning',
            }),
        })
    })

    // The warning is specific to $identify with no anon id to merge from: an $identify that does
    // carry one requests a real merge, and other event types never reach the merge branch at all.
    it.each([
        ['$identify with $anon_distinct_id', '$identify', { $anon_distinct_id: 'user-1' }],
        ['a plain event', '$pageview', {}],
    ])('does not warn for %s', async (_label, event, properties) => {
        await serviceFor(event, properties).handleIdentifyOrAlias()

        expect(emittedWarning()).toBeUndefined()
    })
})
