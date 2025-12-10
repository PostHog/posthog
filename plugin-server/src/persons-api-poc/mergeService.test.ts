import { Person, PersonDistinctIdsApi, PersonPropertiesApi } from './interfaces'
import { PersonMergeServiceImpl } from './mergeService'
import { createBreakpoint, createTestSequence } from './testing'

const createMockPersonPropertiesApi = (): jest.Mocked<PersonPropertiesApi> => ({
    getPersons: jest.fn(),
    mergePersonProperties: jest.fn(),
})

const createMockPersonDistinctIdsApi = (): jest.Mocked<PersonDistinctIdsApi> => ({
    addPersonDistinctId: jest.fn(),
    deletePersonDistinctId: jest.fn(),
    setPersonUuid: jest.fn(),
    setMergingSource: jest.fn(),
    setMergingTarget: jest.fn(),
    setMerged: jest.fn(),
})

describe('PersonMergeServiceImpl', () => {
    let propertiesApi: jest.Mocked<PersonPropertiesApi>
    let distinctIdsApi: jest.Mocked<PersonDistinctIdsApi>
    let mergeService: PersonMergeServiceImpl

    beforeEach(() => {
        propertiesApi = createMockPersonPropertiesApi()
        distinctIdsApi = createMockPersonDistinctIdsApi()
        mergeService = new PersonMergeServiceImpl(propertiesApi, distinctIdsApi)
    })

    it('merges a single source into target', async () => {
        const targetDistinctId = 'target-distinct-id'
        const sourceDistinctId = 'source-distinct-id'
        const targetPersonUuid = 'target-person-uuid'
        const sourcePersonUuid = 'source-person-uuid'
        const version = 1000

        const markTargetAsMerging = createBreakpoint()
        distinctIdsApi.setMergingTarget.mockImplementation(() => {
            markTargetAsMerging.complete(undefined)
            return Promise.resolve({ status: 'ok', distinctId: targetDistinctId, personUuid: targetPersonUuid })
        })

        const markSourceAsMerging = createBreakpoint()
        distinctIdsApi.setMergingSource.mockImplementation(() => {
            markSourceAsMerging.complete(undefined)
            return Promise.resolve([{ status: 'ok', distinctId: sourceDistinctId, personUuid: sourcePersonUuid }])
        })

        const fetchSourcePersons = createBreakpoint()
        const sourcePerson: Person = {
            personUuid: sourcePersonUuid,
            properties: { email: { value: 'source@example.com', version: 1 } },
        }
        propertiesApi.getPersons.mockImplementation(() => {
            fetchSourcePersons.complete(undefined)
            return Promise.resolve(new Map([[sourcePersonUuid, sourcePerson]]))
        })

        const mergePropertiesToTarget = createBreakpoint()
        propertiesApi.mergePersonProperties.mockImplementation(() => {
            mergePropertiesToTarget.complete(undefined)
            return Promise.resolve()
        })

        const markSourceAsMerged = createBreakpoint()
        const markTargetAsMerged = createBreakpoint()
        let setMergedCallCount = 0
        distinctIdsApi.setMerged.mockImplementation((distinctId, personUuid) => {
            setMergedCallCount++
            if (setMergedCallCount === 1) {
                markSourceAsMerged.complete(undefined)
            } else {
                markTargetAsMerged.complete(undefined)
            }
            return Promise.resolve({ distinctId, personUuid })
        })

        const sequence = createTestSequence([
            markTargetAsMerging.wait,
            markSourceAsMerging.wait,
            fetchSourcePersons.wait,
            mergePropertiesToTarget.wait,
            markSourceAsMerged.wait,
            markTargetAsMerged.wait,
        ])

        const mergePromise = mergeService.merge(targetDistinctId, [sourceDistinctId], version)
        await sequence.run()
        const result = await mergePromise

        expect(result).toEqual({
            merged: [{ distinctId: sourceDistinctId, personUuid: targetPersonUuid }],
            conflicts: [],
        })
        expect(distinctIdsApi.setMergingTarget).toHaveBeenCalledWith(targetDistinctId, version)
        expect(distinctIdsApi.setMergingSource).toHaveBeenCalledWith([sourceDistinctId], version)
        expect(propertiesApi.getPersons).toHaveBeenCalledWith([sourcePersonUuid])
        expect(propertiesApi.mergePersonProperties).toHaveBeenCalledWith(targetPersonUuid, [sourcePerson])
        expect(distinctIdsApi.setMerged).toHaveBeenCalledWith(sourceDistinctId, targetPersonUuid, version)
        expect(distinctIdsApi.setMerged).toHaveBeenCalledWith(targetDistinctId, targetPersonUuid, version)
    })

    it('merges multiple sources into target', async () => {
        const targetDistinctId = 'target-distinct-id'
        const sourceDistinctIds = ['source-1', 'source-2', 'source-3']
        const targetPersonUuid = 'target-person-uuid'
        const sourcePersonUuids = ['source-person-1', 'source-person-2', 'source-person-3']
        const version = 2000

        const markTargetAsMerging = createBreakpoint()
        distinctIdsApi.setMergingTarget.mockImplementation(() => {
            markTargetAsMerging.complete(undefined)
            return Promise.resolve({ status: 'ok', distinctId: targetDistinctId, personUuid: targetPersonUuid })
        })

        const markSourcesAsMerging = createBreakpoint()
        distinctIdsApi.setMergingSource.mockImplementation(() => {
            markSourcesAsMerging.complete(undefined)
            return Promise.resolve(
                sourceDistinctIds.map((distinctId, index) => ({
                    status: 'ok' as const,
                    distinctId,
                    personUuid: sourcePersonUuids[index],
                }))
            )
        })

        const fetchSourcePersons = createBreakpoint()
        const sourcePersons: Person[] = sourcePersonUuids.map((uuid, index) => ({
            personUuid: uuid,
            properties: { [`prop${index}`]: { value: `value${index}`, version: 1 } },
        }))
        propertiesApi.getPersons.mockImplementation(() => {
            fetchSourcePersons.complete(undefined)
            return Promise.resolve(new Map(sourcePersons.map((p) => [p.personUuid, p])))
        })

        const mergePropertiesToTarget = createBreakpoint()
        propertiesApi.mergePersonProperties.mockImplementation(() => {
            mergePropertiesToTarget.complete(undefined)
            return Promise.resolve()
        })

        const markSource1AsMerged = createBreakpoint()
        const markSource2AsMerged = createBreakpoint()
        const markSource3AsMerged = createBreakpoint()
        const markTargetAsMerged = createBreakpoint()
        let setMergedCount = 0
        distinctIdsApi.setMerged.mockImplementation((distinctId, personUuid) => {
            setMergedCount++
            if (setMergedCount === 1) {
                markSource1AsMerged.complete(undefined)
            } else if (setMergedCount === 2) {
                markSource2AsMerged.complete(undefined)
            } else if (setMergedCount === 3) {
                markSource3AsMerged.complete(undefined)
            } else {
                markTargetAsMerged.complete(undefined)
            }
            return Promise.resolve({ distinctId, personUuid })
        })

        const sequence = createTestSequence([
            markTargetAsMerging.wait,
            markSourcesAsMerging.wait,
            fetchSourcePersons.wait,
            mergePropertiesToTarget.wait,
            markSource1AsMerged.wait,
            markSource2AsMerged.wait,
            markSource3AsMerged.wait,
            markTargetAsMerged.wait,
        ])

        const mergePromise = mergeService.merge(targetDistinctId, sourceDistinctIds, version)
        await sequence.run()
        const result = await mergePromise

        expect(result.merged).toHaveLength(3)
        expect(result.conflicts).toHaveLength(0)
        expect(distinctIdsApi.setMergingSource).toHaveBeenCalledWith(sourceDistinctIds, version)
        expect(propertiesApi.getPersons).toHaveBeenCalledWith(sourcePersonUuids)
        expect(propertiesApi.mergePersonProperties).toHaveBeenCalledWith(targetPersonUuid, sourcePersons)
        expect(distinctIdsApi.setMerged).toHaveBeenCalledTimes(4)
    })

    it('deduplicates source person UUIDs when multiple distinct IDs belong to same person', async () => {
        const targetDistinctId = 'target-distinct-id'
        const sourceDistinctIds = ['source-1', 'source-2']
        const targetPersonUuid = 'target-person-uuid'
        const sharedSourcePersonUuid = 'shared-source-person-uuid'
        const version = 3000

        const markTargetAsMerging = createBreakpoint()
        distinctIdsApi.setMergingTarget.mockImplementation(() => {
            markTargetAsMerging.complete(undefined)
            return Promise.resolve({ status: 'ok', distinctId: targetDistinctId, personUuid: targetPersonUuid })
        })

        const markSourcesAsMerging = createBreakpoint()
        distinctIdsApi.setMergingSource.mockImplementation(() => {
            markSourcesAsMerging.complete(undefined)
            return Promise.resolve([
                { status: 'ok', distinctId: 'source-1', personUuid: sharedSourcePersonUuid },
                { status: 'ok', distinctId: 'source-2', personUuid: sharedSourcePersonUuid },
            ])
        })

        const fetchSourcePersons = createBreakpoint()
        const sharedSourcePerson: Person = {
            personUuid: sharedSourcePersonUuid,
            properties: { shared: { value: 'property', version: 1 } },
        }
        propertiesApi.getPersons.mockImplementation(() => {
            fetchSourcePersons.complete(undefined)
            return Promise.resolve(new Map([[sharedSourcePersonUuid, sharedSourcePerson]]))
        })

        const mergePropertiesToTarget = createBreakpoint()
        propertiesApi.mergePersonProperties.mockImplementation(() => {
            mergePropertiesToTarget.complete(undefined)
            return Promise.resolve()
        })

        const markSource1AsMerged = createBreakpoint()
        const markSource2AsMerged = createBreakpoint()
        const markTargetAsMerged = createBreakpoint()
        let setMergedCount = 0
        distinctIdsApi.setMerged.mockImplementation((distinctId, personUuid) => {
            setMergedCount++
            if (setMergedCount === 1) {
                markSource1AsMerged.complete(undefined)
            } else if (setMergedCount === 2) {
                markSource2AsMerged.complete(undefined)
            } else {
                markTargetAsMerged.complete(undefined)
            }
            return Promise.resolve({ distinctId, personUuid })
        })

        const sequence = createTestSequence([
            markTargetAsMerging.wait,
            markSourcesAsMerging.wait,
            fetchSourcePersons.wait,
            mergePropertiesToTarget.wait,
            markSource1AsMerged.wait,
            markSource2AsMerged.wait,
            markTargetAsMerged.wait,
        ])

        const mergePromise = mergeService.merge(targetDistinctId, sourceDistinctIds, version)
        await sequence.run()
        await mergePromise

        expect(propertiesApi.getPersons).toHaveBeenCalledTimes(1)
        expect(propertiesApi.getPersons).toHaveBeenCalledWith([sharedSourcePersonUuid])
        expect(propertiesApi.mergePersonProperties).toHaveBeenCalledTimes(1)
    })

    it('handles source person with no properties', async () => {
        const targetDistinctId = 'target-distinct-id'
        const sourceDistinctId = 'source-distinct-id'
        const targetPersonUuid = 'target-person-uuid'
        const sourcePersonUuid = 'source-person-uuid'
        const version = 4000

        const markTargetAsMerging = createBreakpoint()
        distinctIdsApi.setMergingTarget.mockImplementation(() => {
            markTargetAsMerging.complete(undefined)
            return Promise.resolve({ status: 'ok', distinctId: targetDistinctId, personUuid: targetPersonUuid })
        })

        const markSourceAsMerging = createBreakpoint()
        distinctIdsApi.setMergingSource.mockImplementation(() => {
            markSourceAsMerging.complete(undefined)
            return Promise.resolve([{ status: 'ok', distinctId: sourceDistinctId, personUuid: sourcePersonUuid }])
        })

        const fetchSourcePersonsEmpty = createBreakpoint()
        propertiesApi.getPersons.mockImplementation(() => {
            fetchSourcePersonsEmpty.complete(undefined)
            return Promise.resolve(new Map())
        })

        const markSourceAsMerged = createBreakpoint()
        const markTargetAsMerged = createBreakpoint()
        let setMergedCount = 0
        distinctIdsApi.setMerged.mockImplementation((distinctId, personUuid) => {
            setMergedCount++
            if (setMergedCount === 1) {
                markSourceAsMerged.complete(undefined)
            } else {
                markTargetAsMerged.complete(undefined)
            }
            return Promise.resolve({ distinctId, personUuid })
        })

        const sequence = createTestSequence([
            markTargetAsMerging.wait,
            markSourceAsMerging.wait,
            fetchSourcePersonsEmpty.wait,
            markSourceAsMerged.wait,
            markTargetAsMerged.wait,
        ])

        const mergePromise = mergeService.merge(targetDistinctId, [sourceDistinctId], version)
        await sequence.run()
        await mergePromise

        expect(propertiesApi.getPersons).toHaveBeenCalledWith([sourcePersonUuid])
        expect(propertiesApi.mergePersonProperties).not.toHaveBeenCalled()
    })

    it('returns conflicts when source distinct IDs are already merging', async () => {
        const targetDistinctId = 'target-distinct-id'
        const sourceDistinctIds = ['source-1', 'source-2', 'source-3']
        const targetPersonUuid = 'target-person-uuid'
        const version = 5000

        const markTargetAsMerging = createBreakpoint()
        distinctIdsApi.setMergingTarget.mockImplementation(() => {
            markTargetAsMerging.complete(undefined)
            return Promise.resolve({ status: 'ok', distinctId: targetDistinctId, personUuid: targetPersonUuid })
        })

        const markSourcesWithConflicts = createBreakpoint()
        distinctIdsApi.setMergingSource.mockImplementation(() => {
            markSourcesWithConflicts.complete(undefined)
            return Promise.resolve([
                { status: 'ok', distinctId: 'source-1', personUuid: 'person-1' },
                {
                    status: 'conflict',
                    distinctId: 'source-2',
                    personUuid: 'person-2',
                    currentMergeStatus: 'merging_source',
                },
                {
                    status: 'conflict',
                    distinctId: 'source-3',
                    personUuid: 'person-3',
                    currentMergeStatus: 'merging_target',
                },
            ])
        })

        const fetchPersonsForValidSource = createBreakpoint()
        const validSourcePerson: Person = {
            personUuid: 'person-1',
            properties: { prop: { value: 'value', version: 1 } },
        }
        propertiesApi.getPersons.mockImplementation(() => {
            fetchPersonsForValidSource.complete(undefined)
            return Promise.resolve(new Map([['person-1', validSourcePerson]]))
        })

        const mergePropertiesToTarget = createBreakpoint()
        propertiesApi.mergePersonProperties.mockImplementation(() => {
            mergePropertiesToTarget.complete(undefined)
            return Promise.resolve()
        })

        const markValidSourceAsMerged = createBreakpoint()
        const markTargetAsMerged = createBreakpoint()
        let setMergedCount = 0
        distinctIdsApi.setMerged.mockImplementation((distinctId, personUuid) => {
            setMergedCount++
            if (setMergedCount === 1) {
                markValidSourceAsMerged.complete(undefined)
            } else {
                markTargetAsMerged.complete(undefined)
            }
            return Promise.resolve({ distinctId, personUuid })
        })

        const sequence = createTestSequence([
            markTargetAsMerging.wait,
            markSourcesWithConflicts.wait,
            fetchPersonsForValidSource.wait,
            mergePropertiesToTarget.wait,
            markValidSourceAsMerged.wait,
            markTargetAsMerged.wait,
        ])

        const mergePromise = mergeService.merge(targetDistinctId, sourceDistinctIds, version)
        await sequence.run()
        const result = await mergePromise

        expect(result).toEqual({
            merged: [{ distinctId: 'source-1', personUuid: targetPersonUuid }],
            conflicts: [
                { type: 'source_already_merging_elsewhere', distinctId: 'source-2', personUuid: 'person-2' },
                { type: 'source_is_merge_target', distinctId: 'source-3', personUuid: 'person-3' },
            ],
        })
        expect(propertiesApi.getPersons).toHaveBeenCalledWith(['person-1'])
        expect(distinctIdsApi.setMerged).toHaveBeenCalledWith('source-1', targetPersonUuid, version)
        expect(distinctIdsApi.setMerged).not.toHaveBeenCalledWith('source-2', expect.anything(), expect.anything())
        expect(distinctIdsApi.setMerged).not.toHaveBeenCalledWith('source-3', expect.anything(), expect.anything())
    })

    it('clears target merge status when all sources conflict', async () => {
        const targetDistinctId = 'target-distinct-id'
        const targetPersonUuid = 'target-person-uuid'
        const sourceDistinctIds = ['source-1', 'source-2']
        const version = 6000

        const markTargetAsMerging = createBreakpoint()
        distinctIdsApi.setMergingTarget.mockImplementation(() => {
            markTargetAsMerging.complete(undefined)
            return Promise.resolve({ status: 'ok', distinctId: targetDistinctId, personUuid: targetPersonUuid })
        })

        const allSourcesConflict = createBreakpoint()
        distinctIdsApi.setMergingSource.mockImplementation(() => {
            allSourcesConflict.complete(undefined)
            return Promise.resolve([
                {
                    status: 'conflict',
                    distinctId: 'source-1',
                    personUuid: 'person-1',
                    currentMergeStatus: 'merging_source',
                },
                {
                    status: 'conflict',
                    distinctId: 'source-2',
                    personUuid: 'person-2',
                    currentMergeStatus: 'merging_target',
                },
            ])
        })

        const clearTargetMergeStatus = createBreakpoint()
        distinctIdsApi.setMerged.mockImplementation((distinctId, personUuid) => {
            clearTargetMergeStatus.complete(undefined)
            return Promise.resolve({ distinctId, personUuid })
        })

        const sequence = createTestSequence([
            markTargetAsMerging.wait,
            allSourcesConflict.wait,
            clearTargetMergeStatus.wait,
        ])

        const mergePromise = mergeService.merge(targetDistinctId, sourceDistinctIds, version)
        await sequence.run()
        const result = await mergePromise

        expect(result).toEqual({
            merged: [],
            conflicts: [
                { type: 'source_already_merging_elsewhere', distinctId: 'source-1', personUuid: 'person-1' },
                { type: 'source_is_merge_target', distinctId: 'source-2', personUuid: 'person-2' },
            ],
        })
        expect(distinctIdsApi.setMergingTarget).toHaveBeenCalledWith(targetDistinctId, version)
        expect(distinctIdsApi.setMerged).toHaveBeenCalledWith(targetDistinctId, targetPersonUuid, version)
        expect(propertiesApi.getPersons).not.toHaveBeenCalled()
    })

    it('returns conflict when target is being merged into another distinct ID', async () => {
        const targetDistinctId = 'target-distinct-id'
        const sourceDistinctIds = ['source-1']
        const version = 7000

        const targetAlreadyMergingElsewhere = createBreakpoint()
        distinctIdsApi.setMergingTarget.mockImplementation(() => {
            targetAlreadyMergingElsewhere.complete(undefined)
            return Promise.resolve({
                status: 'conflict',
                distinctId: targetDistinctId,
                personUuid: 'target-person-uuid',
                mergingIntoDistinctId: 'other-target-distinct-id',
            })
        })

        const sequence = createTestSequence([targetAlreadyMergingElsewhere.wait])

        const mergePromise = mergeService.merge(targetDistinctId, sourceDistinctIds, version)
        await sequence.run()
        const result = await mergePromise

        expect(result).toEqual({
            merged: [],
            conflicts: [
                {
                    type: 'target_is_source_in_another_merge',
                    distinctId: targetDistinctId,
                    personUuid: 'target-person-uuid',
                    mergingIntoDistinctId: 'other-target-distinct-id',
                },
            ],
        })
        expect(distinctIdsApi.setMergingSource).not.toHaveBeenCalled()
        expect(propertiesApi.getPersons).not.toHaveBeenCalled()
        expect(distinctIdsApi.setMerged).not.toHaveBeenCalled()
    })
})
