import { DataModelingNode } from '~/types'

import { modelsBehindSchedule } from './freshness'

const NOW = new Date('2026-09-09T12:00:00Z').getTime()
const hoursAgo = (h: number): string => new Date(NOW - h * 3600 * 1000).toISOString()

function node(name: string, overrides: Partial<DataModelingNode> = {}): DataModelingNode {
    return {
        id: name,
        name,
        type: 'matview',
        sync_interval: '1hour',
        last_run_at: hoursAgo(1),
        created_at: hoursAgo(100),
        ...overrides,
    } as DataModelingNode
}

describe('modelsBehindSchedule', () => {
    it('keeps a model that missed more than one scheduled run', () => {
        const behind = modelsBehindSchedule([node('late', { last_run_at: hoursAgo(5) })], NOW)

        expect(behind.map((row) => row.node.name)).toEqual(['late'])
        expect(behind[0].intervalSeconds).toEqual(3600)
    })

    it.each([
        ['a run is merely due', hoursAgo(1.5)],
        ['a run is exactly two intervals old', hoursAgo(2)],
    ])('leaves a model alone when %s', (_label, lastRunAt) => {
        expect(modelsBehindSchedule([node('fresh', { last_run_at: lastRunAt })], NOW)).toEqual([])
    })

    it.each([
        ['it declares no refresh target, which is how a model is paused', { sync_interval: undefined }],
        ['it is a plain view, which stores nothing that can go stale', { type: 'view' as const }],
    ])('leaves a model alone when %s', (_label, overrides) => {
        const stale = node('stale', { last_run_at: hoursAgo(500), ...overrides })

        expect(modelsBehindSchedule([stale], NOW)).toEqual([])
    })

    it('measures a model that has never finished a run from when it was created', () => {
        const never = node('never', { last_run_at: null, created_at: hoursAgo(10) })

        const behind = modelsBehindSchedule([never], NOW)

        expect(behind).toHaveLength(1)
        expect(behind[0].ageSeconds).toEqual(10 * 3600)
    })

    it('puts the model that missed the most runs first, not the oldest one', () => {
        const daily = node('daily', { sync_interval: '24hour', last_run_at: hoursAgo(96) })
        const hourly = node('hourly', { sync_interval: '1hour', last_run_at: hoursAgo(20) })

        expect(modelsBehindSchedule([daily, hourly], NOW).map((row) => row.node.name)).toEqual(['hourly', 'daily'])
    })
})
