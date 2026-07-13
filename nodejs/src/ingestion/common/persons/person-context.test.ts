import { DateTime } from 'luxon'

import { buildIntegerMatcher } from '~/common/config/config'
import { PERSON_MERGE_EVENTS_OUTPUT } from '~/common/outputs'
import { UUIDT } from '~/common/utils/utils'
import { InternalPerson } from '~/types'

import { MergeEventsConfig, PersonContext } from './person-context'
import { createDefaultSyncMergeMode } from './person-merge-types'

describe('PersonContext', () => {
    let mockOutputs: { produce: jest.Mock }

    const sourcePerson = { uuid: '01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee' } as InternalPerson
    const targetPerson = { uuid: '01928bbb-cccc-dddd-eeee-ffffffffffff' } as InternalPerson

    function buildContext(teamId: number, mergeEventsConfig: MergeEventsConfig): PersonContext {
        mockOutputs = { produce: jest.fn().mockResolvedValue(undefined) }
        return new PersonContext(
            { uuid: new UUIDT().toString(), distinct_id: 'd', properties: {} } as any,
            { id: teamId } as any,
            'd',
            DateTime.now(),
            true,
            mockOutputs as any,
            {} as any,
            0,
            createDefaultSyncMergeMode(),
            false,
            false,
            mergeEventsConfig
        )
    }

    // The producer must never emit for teams outside the allowlist (the whole point of the gate):
    // a regression that widened it would flood the cohort-stream-processor with out-of-scope events.
    it.each([
        {
            name: 'disabled: no-op even for an allowlisted team',
            enabled: false,
            allowlist: '2',
            teamId: 2,
            produces: false,
        },
        {
            name: 'enabled + team in the default allowlist produces',
            enabled: true,
            allowlist: '2',
            teamId: 2,
            produces: true,
        },
        {
            name: 'enabled + team outside the allowlist is a no-op',
            enabled: true,
            allowlist: '2',
            teamId: 99,
            produces: false,
        },
        {
            name: 'enabled + wildcard allowlist produces for any team',
            enabled: true,
            allowlist: '*',
            teamId: 99,
            produces: true,
        },
        {
            // Node treats an empty allowlist as match-nothing, the opposite of Rust's "empty means all".
            // Clearing the env var expecting the Rust behavior silently stops all emission.
            name: 'enabled + empty allowlist is a no-op (empty matches no teams)',
            enabled: true,
            allowlist: '',
            teamId: 2,
            produces: false,
        },
    ])('producePersonMergeEvent $name', async ({ enabled, allowlist, teamId, produces }) => {
        const context = buildContext(teamId, {
            enabled,
            partitionCount: 64,
            isTeamEnabled: buildIntegerMatcher(allowlist, true),
        })

        await context.producePersonMergeEvent(sourcePerson, targetPerson)

        if (produces) {
            expect(mockOutputs.produce).toHaveBeenCalledTimes(1)
            expect(mockOutputs.produce).toHaveBeenCalledWith(
                PERSON_MERGE_EVENTS_OUTPUT,
                expect.objectContaining({ teamId })
            )
        } else {
            expect(mockOutputs.produce).not.toHaveBeenCalled()
        }
    })
})
