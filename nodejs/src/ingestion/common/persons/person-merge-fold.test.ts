import { isOkResult } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, Team } from '~/types'

import { MergeFoldScanItem, createMergeFoldPlanningStep } from './person-merge-fold'

describe('createMergeFoldPlanningStep', () => {
    const team = { id: 7 } as Team

    let uuidCounter: number

    beforeEach(() => {
        uuidCounter = 0
    })

    function identify(anonDistinctId: string, distinctId = 'user-1'): MergeFoldScanItem {
        return event('$identify', distinctId, { $anon_distinct_id: anonDistinctId })
    }

    function event(
        name: string,
        distinctId = 'user-1',
        properties: Record<string, unknown> = {},
        headers: Partial<EventHeaders> = {}
    ): MergeFoldScanItem {
        return {
            event: {
                event: name,
                distinct_id: distinctId,
                uuid: `uuid-${uuidCounter++}`,
                properties,
            } as unknown as PluginEvent,
            team,
            headers: headers as EventHeaders,
        }
    }

    async function scan(
        values: MergeFoldScanItem[],
        options: { enabled?: boolean; allowlist?: string } = {}
    ): Promise<MergeFoldScanItem[]> {
        const step = createMergeFoldPlanningStep({
            PERSON_MERGE_FOLD_ENABLED: options.enabled ?? true,
            PERSON_MERGE_FOLD_TEAM_ALLOWLIST: options.allowlist ?? '*',
        })
        const results = await step(values)
        expect(results).toHaveLength(values.length)
        return results.map((result) => {
            if (!isOkResult(result)) {
                throw new Error('planning step must not fail values')
            }
            return result.value
        })
    }

    it('passes values through unplanned when folding is disabled', async () => {
        const inputs = [identify('anon-1'), identify('anon-2')]
        const items = await scan(inputs, { enabled: false })

        expect(items).toEqual(inputs)
        expect(items.every((item) => item.mergeFoldPlan === undefined)).toBe(true)
    })

    it('plans one shared fold for a run of identifies with distinct anon ids', async () => {
        const items = await scan([identify('anon-1'), identify('anon-2'), identify('anon-3')])

        const plan = items[0].mergeFoldPlan
        expect(plan).toBeDefined()
        expect(items.every((item) => item.mergeFoldPlan === plan)).toBe(true)
        expect(plan).toMatchObject({
            targetDistinctId: 'user-1',
            status: 'planned',
            pairs: [
                { anonDistinctId: 'anon-1', eventUuid: 'uuid-0' },
                { anonDistinctId: 'anon-2', eventUuid: 'uuid-1' },
                { anonDistinctId: 'anon-3', eventUuid: 'uuid-2' },
            ],
        })
    })

    it('annotates planned values without mutating the inputs', async () => {
        const inputs = [identify('anon-1'), identify('anon-2'), event('$pageview')]
        const items = await scan(inputs)

        expect(inputs.every((input) => input.mergeFoldPlan === undefined)).toBe(true)
        expect(items[0].mergeFoldPlan).toBeDefined()
        // Values outside the planned run pass through as the same object.
        expect(items[2]).toBe(inputs[2])
    })

    it('dedupes repeated pairs, keeping the first event uuid', async () => {
        const items = await scan([identify('anon-1'), identify('anon-1'), identify('anon-2')])

        expect(items[0].mergeFoldPlan?.pairs).toEqual([
            { anonDistinctId: 'anon-1', eventUuid: 'uuid-0' },
            { anonDistinctId: 'anon-2', eventUuid: 'uuid-2' },
        ])
        expect(items[1].mergeFoldPlan).toBe(items[0].mergeFoldPlan)
    })

    it('does not plan a single merge event', async () => {
        const items = await scan([identify('anon-1'), event('$pageview')])

        expect(items.every((item) => item.mergeFoldPlan === undefined)).toBe(true)
    })

    it('splits runs on interleaved non-merge events', async () => {
        const items = await scan([
            identify('anon-1'),
            identify('anon-2'),
            event('$pageview'),
            identify('anon-3'),
            identify('anon-4'),
        ])

        const firstPlan = items[0].mergeFoldPlan
        const secondPlan = items[3].mergeFoldPlan
        expect(firstPlan?.pairs.map((p) => p.anonDistinctId)).toEqual(['anon-1', 'anon-2'])
        expect(secondPlan?.pairs.map((p) => p.anonDistinctId)).toEqual(['anon-3', 'anon-4'])
        expect(firstPlan).not.toBe(secondPlan)
        expect(items[2].mergeFoldPlan).toBeUndefined()
    })

    it.each([
        ['$create_alias', { alias: 'anon-1' }],
        ['$merge_dangerously', { alias: 'anon-1' }],
        ['$identify', {}],
    ])('does not treat %s as foldable', async (name, properties) => {
        const items = await scan([event(name, 'user-1', properties), identify('anon-2'), identify('anon-3')])

        expect(items[0].mergeFoldPlan).toBeUndefined()
        expect(items[1].mergeFoldPlan?.pairs.map((p) => p.anonDistinctId)).toEqual(['anon-2', 'anon-3'])
    })

    it.each([
        [
            '$process_person_profile: false',
            (anonDistinctId: string) =>
                event('$identify', 'user-1', { $anon_distinct_id: anonDistinctId, $process_person_profile: false }),
        ],
        [
            'force_disable_person_processing header',
            (anonDistinctId: string) =>
                event(
                    '$identify',
                    'user-1',
                    { $anon_distinct_id: anonDistinctId },
                    { force_disable_person_processing: true }
                ),
        ],
    ])('does not fold an $identify with %s and splits the run on it', async (_name, disabledIdentify) => {
        const items = await scan([
            identify('anon-1'),
            identify('anon-2'),
            disabledIdentify('anon-3'),
            identify('anon-4'),
        ])

        const plan = items[0].mergeFoldPlan
        expect(plan?.pairs.map((p) => p.anonDistinctId)).toEqual(['anon-1', 'anon-2'])
        expect(items[2].mergeFoldPlan).toBeUndefined()
        // anon-4 is a lone identify after the split, so nothing to fold.
        expect(items[3].mergeFoldPlan).toBeUndefined()
    })

    it('excludes illegal anon distinct ids from the plan without splitting the run', async () => {
        const items = await scan([identify('anon-1'), identify('anonymous'), identify('anon-2')])

        const plan = items[0].mergeFoldPlan
        expect(plan?.pairs.map((p) => p.anonDistinctId)).toEqual(['anon-1', 'anon-2'])
        expect(items[1].mergeFoldPlan).toBeUndefined()
        expect(items[2].mergeFoldPlan).toBe(plan)
    })

    it('skips planning when only illegal anon distinct ids are in the run', async () => {
        const items = await scan([identify('anonymous'), identify('null')])

        expect(items.every((item) => item.mergeFoldPlan === undefined)).toBe(true)
    })

    it('excludes self-merges from the plan', async () => {
        const items = await scan([identify('user-1'), identify('anon-1'), identify('anon-2')])

        expect(items[0].mergeFoldPlan).toBeUndefined()
        expect(items[1].mergeFoldPlan?.pairs.map((p) => p.anonDistinctId)).toEqual(['anon-1', 'anon-2'])
    })

    it('skips planning when only self-merges are in the run', async () => {
        const items = await scan([identify('user-1'), identify('user-1')])

        expect(items.every((item) => item.mergeFoldPlan === undefined)).toBe(true)
    })

    it('respects the team allowlist', async () => {
        const planned = await scan([identify('anon-1'), identify('anon-2')], { allowlist: '7' })
        expect(planned[0].mergeFoldPlan).toBeDefined()

        const skipped = await scan([identify('anon-1'), identify('anon-2')], { allowlist: '8,9' })
        expect(skipped.every((item) => item.mergeFoldPlan === undefined)).toBe(true)
    })
})
