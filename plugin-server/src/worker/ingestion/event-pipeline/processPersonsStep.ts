import { PluginEvent } from '@posthog/plugin-scaffold'
import { ProducerRecord } from 'kafkajs'
import { DateTime } from 'luxon'
import { Person } from 'types'

import { PostgresUse } from '../../../utils/db/postgres'
import { timeoutGuard } from '../../../utils/db/utils'
import { normalizeEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import { DeferredPersonOverrideWriter, PersonOverrideWriter, PersonState } from '../person-state'
import { parseEventTimestamp } from '../timestamps'
import { EventPipelineRunner } from './runner'

export async function processPersonsStep(
    runner: EventPipelineRunner,
    pluginEvent: PluginEvent
): Promise<[PluginEvent, Person | null]> {
    let event: PluginEvent
    let timestamp: DateTime
    try {
        event = normalizeEvent(pluginEvent)
        timestamp = parseEventTimestamp(event)
    } catch (error) {
        status.warn('⚠️', 'Failed normalizing event', { team_id: pluginEvent.team_id, uuid: pluginEvent.uuid, error })
        throw error
    }

    if (pluginEvent.event === '$delete_person') {
        const timeout = timeoutGuard('Still running "$delete_person". Timeout warning after 30 sec!')
        try {
            const person = await runner.hub.db.fetchPerson(pluginEvent.team_id, pluginEvent.distinct_id)
            if (!person) {
                return [event, null]
            }

            const kafkaMessages: ProducerRecord[] = await runner.hub.db.postgres.transaction(
                PostgresUse.COMMON_WRITE,
                'mergePeople',
                async (tx) => {
                    const personDeleteMessages = await runner.hub.db.deletePerson(person, tx)
                    const personDistinctIdDeleteMessages = await runner.hub.db.deleteDistinctIds(person, tx)
                    console.log(pluginEvent.properties)
                    if (pluginEvent.properties!['delete_events']) {
                        const creatorId = pluginEvent.properties!['created_by_id']
                        await runner.hub.db.asyncEventsDeletion(person, creatorId, tx)
                    }
                    return [...personDeleteMessages, ...personDistinctIdDeleteMessages]
                }
            )
            await runner.hub.db.kafkaProducer.queueMessages(kafkaMessages)
            // TODO: add tests

            // def test_delete_person(self):
            //     person = Person.objects.create(
            //         team=self.team, version=15
            //     )  # version be > 0 to check that we don't just assume 0 in deletes
            //     delete_person(person, sync=True)
            //     ch_persons = sync_execute(
            //         "SELECT toString(id), version, is_deleted, properties FROM person FINAL WHERE team_id = %(team_id)s and id = %(uuid)s",
            //         {"team_id": self.team.pk, "uuid": person.uuid},
            //     )
            //     self.assertEqual(ch_persons, [(str(person.uuid), 115, 1, "{}")])

            // def test_delete_ch_distinct_ids(self):
            //     person = Person.objects.create(team=self.team)
            //     PersonDistinctId.objects.create(team=self.team, person=person, distinct_id="distinct_id1", version=15)

            //     ch_distinct_ids = sync_execute(
            //         "SELECT is_deleted FROM person_distinct_id2 FINAL WHERE team_id = %(team_id)s and distinct_id = %(distinct_id)s",
            //         {"team_id": self.team.pk, "distinct_id": "distinct_id1"},
            //     )
            //     self.assertEqual(ch_distinct_ids, [(0,)])

            //     delete_person(person, sync=True)
            //     ch_distinct_ids = sync_execute(
            //         "SELECT toString(person_id), version, is_deleted FROM person_distinct_id2 FINAL WHERE team_id = %(team_id)s and distinct_id = %(distinct_id)s",
            //         {"team_id": self.team.pk, "distinct_id": "distinct_id1"},
            //     )
            //     self.assertEqual(ch_distinct_ids, [(str(person.uuid), 115, 1)])
        } finally {
            clearTimeout(timeout)
        }
        return [event, null]
    }

    let overridesWriter: PersonOverrideWriter | DeferredPersonOverrideWriter | undefined = undefined
    if (runner.poEEmbraceJoin) {
        if (runner.hub.POE_DEFERRED_WRITES_ENABLED) {
            overridesWriter = new DeferredPersonOverrideWriter(runner.hub.db.postgres)
        } else {
            overridesWriter = new PersonOverrideWriter(runner.hub.db.postgres)
        }
    }

    const person = await new PersonState(
        event,
        event.team_id,
        String(event.distinct_id),
        timestamp,
        runner.hub.db,
        overridesWriter
    ).update()

    return [event, person]
}
