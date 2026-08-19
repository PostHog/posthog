import { createMockJobQueue } from '../../../tests/helpers/mocks/job-queue.mock'
import '../../../tests/helpers/mocks/producer.mock'

import { GroupReadRepository } from '~/common/groups/repositories/group-repository.interface'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { forSnapshot } from '~/tests/helpers/snapshots'

import { createCdpConsumerDeps } from '../../../tests/helpers/cdp'
import { getFirstTeam, resetTestDatabase, updateOrganizationAvailableFeatures } from '../../../tests/helpers/sql'
import { ClickhouseGroup, Hub, Team } from '../../types'
import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import { insertHogFunction as _insertHogFunction, createHogFunction, createKafkaMessage } from '../_tests/fixtures'
import { insertHogFlow as _insertHogFlow } from '../_tests/fixtures-hogflows'
import { GroupsManagerService } from '../services/managers/groups-manager.service'
import { HogFunctionType } from '../types'
import { CdpGroupUpdatesConsumer } from './cdp-group-updates.consumer'

describe('CDP Group Updates Consumer', () => {
    let processor: CdpGroupUpdatesConsumer
    let hub: Hub
    let team: Team
    let hogFunction: HogFunctionType

    const createClickhouseGroup = (teamId: number, data: Partial<ClickhouseGroup> = {}): ClickhouseGroup => ({
        team_id: teamId,
        group_type_index: 0,
        group_key: 'acme-inc',
        created_at: '2025-01-01 00:00:00',
        group_properties: JSON.stringify({ name: 'Acme Inc' }),
        ...data,
    })

    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const item = await _insertHogFunction(hub.postgres, team.id, hogFunction)
        // Trigger the reload that django would do
        processor['hogFunctionManager']['onHogFunctionsReloaded'](team.id, [item.id])
        return item
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub({
            SITE_URL: 'http://localhost:8000',
        })
        team = await getFirstTeam(hub.postgres)
        await updateOrganizationAvailableFeatures(hub.postgres, team.organization_id, [
            { key: 'group_analytics', name: 'Group Analytics' },
        ])
        hub.teamManager['lazyLoader'].clear()

        processor = new CdpGroupUpdatesConsumer(hub, createCdpConsumerDeps(hub), {
            hogQueue: createMockJobQueue(),
            hogflowQueue: createMockJobQueue(),
        })
        await processor.start()

        const mockGroupRepository: GroupReadRepository = {
            fetchGroupsByKeys: jest.fn().mockResolvedValue([]),
            fetchGroupTypesByTeamIds: jest.fn().mockResolvedValue({
                [team.id]: [{ group_type: 'organization', group_type_index: 0 }],
            }),
            fetchGroupTypesByProjectIds: jest.fn().mockResolvedValue({}),
        }
        processor['groupsManager'] = new GroupsManagerService(hub.teamManager, mockGroupRepository)

        hogFunction = createHogFunction({
            // Inputs must not reference `person` - a group update has no person to resolve
            ...HOG_EXAMPLES.simple_return_object,
            ...HOG_INPUTS_EXAMPLES.none,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            type: 'destination',
        })

        hogFunction.filters = { ...hogFunction.filters, source: 'group-updates' }
        await insertHogFunction(hogFunction)
    })

    afterEach(async () => {
        await processor.stop()
        await closeHub(hub)
    })

    describe('_parseKafkaBatch', () => {
        it('should ignore invalid message', async () => {
            const events = await processor._parseKafkaBatch([createKafkaMessage({})])
            expect(events).toHaveLength(0)
        })

        it('should ignore message with no team', async () => {
            const events = await processor._parseKafkaBatch([createKafkaMessage(createClickhouseGroup(999999))])
            expect(events).toHaveLength(0)
        })

        it('should ignore message for an unknown group type index', async () => {
            const events = await processor._parseKafkaBatch([
                createKafkaMessage(createClickhouseGroup(team.id, { group_type_index: 3 })),
            ])
            expect(events).toHaveLength(0)
        })

        it('should key the group by its type name so group property filters resolve', async () => {
            const events = await processor._parseKafkaBatch([
                createKafkaMessage(createClickhouseGroup(team.id), { timestamp: 1735693261000 }),
            ])

            expect(events).toHaveLength(1)
            expect(forSnapshot(events[0])).toMatchInlineSnapshot(`
                {
                  "event": {
                    "distinct_id": "acme-inc",
                    "elements_chain": "",
                    "event": "$group_updated",
                    "properties": {
                      "$groups": {
                        "organization": "acme-inc",
                      },
                    },
                    "timestamp": "2025-01-01T01:01:01.000Z",
                    "url": "http://localhost:8000/project/2/groups/0/acme-inc",
                    "uuid": "<REPLACED-UUID-0>",
                  },
                  "groups": {
                    "organization": {
                      "id": "acme-inc",
                      "index": 0,
                      "properties": {
                        "name": "Acme Inc",
                      },
                      "type": "organization",
                      "url": "http://localhost:8000/project/2/groups/0/acme-inc",
                    },
                  },
                  "project": {
                    "id": 2,
                    "name": "TEST PROJECT",
                    "url": "http://localhost:8000/project/2",
                  },
                }
            `)
        })
    })

    describe('workflows', () => {
        const buildGroupUpdatesHogFlow = (groupTypeIndex: number) =>
            new FixtureHogFlowBuilder()
                .withTeamId(team.id)
                .withSimpleWorkflow({
                    trigger: {
                        type: 'group-updates',
                        group_type_index: groupTypeIndex,
                        filters: { properties: [], bytecode: ['_h', 29] } as any,
                    },
                })
                .build()

        it.each([
            ['matching the updated group type', 0, 1],
            ['subscribed to a different group type', 1, 0],
        ])('builds %s workflow invocations for a group type index of %s', async (_name, groupTypeIndex, expected) => {
            await _insertHogFlow(hub.postgres, buildGroupUpdatesHogFlow(groupTypeIndex))

            const events = await processor._parseKafkaBatch([createKafkaMessage(createClickhouseGroup(team.id))])
            const { invocations } = await processor.processBatch(events)

            expect(invocations.filter((invocation: any) => invocation.hogFlow)).toHaveLength(expected)
        })
    })

    describe('processing', () => {
        it('should only run hog functions that are filtering for group updates', async () => {
            const hogFunctionEvents = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
                type: 'destination',
            })

            await insertHogFunction(hogFunctionEvents)

            const events = await processor._parseKafkaBatch([createKafkaMessage(createClickhouseGroup(team.id))])
            const result = await processor.processBatch(events)

            expect(result.invocations).toHaveLength(1)
            expect(result.invocations[0].functionId).toEqual(hogFunction.id)
        })
    })
})
