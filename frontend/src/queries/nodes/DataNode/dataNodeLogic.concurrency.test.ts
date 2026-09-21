import { Scene } from 'scenes/sceneTypes'

import { getConcurrencyController } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode, NodeKind } from '~/queries/schema/schema-general'
import { TeamType } from '~/types'

let activeSceneId: Scene | null = null

// jest.setup.ts replaces the controller with a pass-through that carries no limit, and the limit is
// what tells the pools apart here.
jest.mock('lib/utils/concurrencyController', () => jest.requireActual('lib/utils/concurrencyController'))

jest.mock('scenes/sceneLogic', () => ({
    sceneLogic: {
        findMounted: () => ({ values: { activeSceneId } }),
    },
}))

const preAggregatedTeam = { modifiers: { useWebAnalyticsPreAggregatedTables: true } } as unknown as TeamType
const liveTeam = { modifiers: {} } as unknown as TeamType

const query = (kind: NodeKind): DataNode => ({ kind }) as DataNode

describe('dataNodeLogic concurrency routing', () => {
    afterEach(() => {
        activeSceneId = null
    })

    // A tile whose query kind sits outside the pre-aggregated set used to fall through to the
    // app-wide controller, which runs one query at a time, so those tiles waited behind each other.
    it.each([
        ['pre-aggregated team', preAggregatedTeam],
        ['live team', liveTeam],
    ])('runs every web analytics tile in one parallel pool for a %s', (_name, team) => {
        activeSceneId = Scene.WebAnalytics

        const preAggregatedKind = getConcurrencyController(query(NodeKind.WebOverviewQuery), team)
        const otherKind = getConcurrencyController(query(NodeKind.WebGoalsQuery), team)

        expect(otherKind).toBe(preAggregatedKind)
        expect(otherKind._concurrencyLimit).toBeGreaterThan(1)
    })

    it('keeps web analytics query kinds off the scene in the pre-aggregated pool', () => {
        activeSceneId = Scene.Dashboard

        expect(
            getConcurrencyController(query(NodeKind.WebOverviewQuery), preAggregatedTeam)._concurrencyLimit
        ).toBeGreaterThan(1)
    })

    it('leaves unrelated queries off the scene in the app-wide pool', () => {
        activeSceneId = Scene.Dashboard

        expect(getConcurrencyController(query(NodeKind.TrendsQuery), liveTeam)._concurrencyLimit).toEqual(1)
    })
})
