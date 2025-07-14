import { DateTime } from 'luxon'

import { resetTestDatabaseClickhouse } from '~/tests/helpers/clickhouse'
import {
    createOrganization,
    createPerson,
    createTeam,
    fetchPersonDistinctIds,
    fetchPostgresPersons,
    resetTestDatabase,
} from '~/tests/helpers/sql'
import { Hub } from '~/types'
import { createHub } from '~/utils/db/hub'
import { UUIDT } from '~/utils/utils'

jest.setTimeout(30000)

describe('person merge', () => {
    let hub: Hub
    let organizationId: string
    let teamId: number
    let timestamp: DateTime
    let firstUserUuid: string
    let firstUserDistinctId: string
    let secondUserUuid: string
    let secondUserDistinctId: string

    beforeAll(async () => {
        hub = await createHub({})
        resetTestDatabase()
        resetTestDatabaseClickhouse()
        await hub.db.clickhouseQuery('SYSTEM STOP MERGES')

        organizationId = await createOrganization(hub.db.postgres)
    })

    beforeEach(async () => {
        hub = await createHub()
        teamId = await createTeam(hub.db.postgres, organizationId)
        timestamp = DateTime.fromISO('2020-01-01T12:00:05.200Z').toUTC()
        firstUserUuid = new UUIDT().toString()
        firstUserDistinctId = 'firstUserDistinctId'
        secondUserUuid = new UUIDT().toString()
        secondUserDistinctId = 'secondUserDistinctId'
    })

    it('should handle race condition when source person provided has been merged to another person', async () => {
        const thirdUserUuid = new UUIDT().toString()
        const thirdUserDistinctId = 'thirdUserDistinctId'
        const personToMerge = await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, firstUserUuid, [
            { distinctId: firstUserDistinctId },
        ])
        const mergeTarget1 = await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, secondUserUuid, [
            { distinctId: secondUserDistinctId },
        ])
        const mergeTarget2 = await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, thirdUserUuid, [
            { distinctId: thirdUserDistinctId },
        ])

        // First merge should work correctly
        const [distinctIdMessages, sourcePersonNotFound] = await hub.db.moveDistinctIds(
            personToMerge.id,
            firstUserDistinctId,
            mergeTarget1.id,
            teamId,
            mergeTarget1.uuid,
            secondUserDistinctId
        )
        expect(distinctIdMessages.length).toBe(1)
        expect(sourcePersonNotFound).toBe(false)
        // delete personToMerge
        await hub.db.deletePerson(personToMerge)

        // Second merge should retry and succeed
        const [distinctIdMessages2, sourcePersonNotFound2] = await hub.db.moveDistinctIds(
            personToMerge.id,
            thirdUserDistinctId,
            mergeTarget2.id,
            teamId,
            mergeTarget2.uuid,
            thirdUserDistinctId
        )
        expect(distinctIdMessages2.length).toBe(1)
        expect(sourcePersonNotFound2).toBe(true)

        const persons = await fetchPostgresPersons(hub.db, teamId)
        expect(persons).toEqual(expect.arrayContaining([mergeTarget2, mergeTarget1]))
        const distinctIdPersonToMerge = await fetchPersonDistinctIds(hub.db, teamId, personToMerge.id)
        expect(distinctIdPersonToMerge).toEqual([])
        const distinctIdMergeTarget1 = await fetchPersonDistinctIds(hub.db, teamId, mergeTarget1.id)
        expect(distinctIdMergeTarget1).toEqual([firstUserDistinctId, secondUserDistinctId])
        const distinctIdMergeTarget2 = await fetchPersonDistinctIds(hub.db, teamId, mergeTarget2.id)
        expect(distinctIdMergeTarget2).toEqual([thirdUserDistinctId])
    })

    it('should handle race condition when target person provided has been merged to another person', async () => {
        const thirdUserUuid = new UUIDT().toString()
        const thirdUserDistinctId = 'thirdUserDistinctId'
        const personToMerge = await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, firstUserUuid, [
            { distinctId: firstUserDistinctId },
        ])
        const mergeTarget1 = await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, secondUserUuid, [
            { distinctId: secondUserDistinctId },
        ])
        const personToMerge2 = await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, thirdUserUuid, [
            { distinctId: thirdUserDistinctId },
        ])

        // First merge should work correctly
        const [distinctIdMessages, sourcePersonNotFound] = await hub.db.moveDistinctIds(
            personToMerge.id,
            firstUserDistinctId,
            mergeTarget1.id,
            teamId,
            mergeTarget1.uuid,
            secondUserDistinctId
        )
        expect(distinctIdMessages.length).toBe(1)
        expect(sourcePersonNotFound).toBe(false)
        // delete personToMerge
        await hub.db.deletePerson(personToMerge)

        // Spy on moveDistinctIdsInner but don't return mock
        jest.spyOn(hub.db, '_moveDistinctIdsInner')
        jest.spyOn(hub.db, 'fetchPersonIdsById')
        // Second merge should retry and succeed
        const [distinctIdMessages2, sourcePersonNotFound2] = await hub.db.moveDistinctIds(
            personToMerge2.id,
            thirdUserDistinctId,
            personToMerge.id,
            teamId,
            personToMerge.uuid,
            firstUserDistinctId
        )
        expect(distinctIdMessages2.length).toBe(1)
        expect(sourcePersonNotFound2).toBe(false)

        // assert moveDistinctIdsInner was called twice
        expect(hub.db._moveDistinctIdsInner).toHaveBeenCalledTimes(2)
        expect(hub.db.fetchPersonIdsById).toHaveBeenCalledTimes(1)

        const persons = await fetchPostgresPersons(hub.db, teamId)
        expect(persons).toEqual(expect.arrayContaining([mergeTarget1]))
        const distinctIdMergeTarget1 = await fetchPersonDistinctIds(hub.db, teamId, mergeTarget1.id)
        expect(distinctIdMergeTarget1).toEqual([firstUserDistinctId, secondUserDistinctId, thirdUserDistinctId])
    })
})
