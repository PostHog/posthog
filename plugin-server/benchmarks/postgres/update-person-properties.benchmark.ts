import { DateTime } from 'luxon'
import { performance } from 'perf_hooks'

import { Hub, PersonPropertyUpdateOperation, Team } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { UUIDT } from '../../src/utils/utils'
import { getFirstTeam, resetTestDatabase } from '../../tests/helpers/sql'

jest.setTimeout(1200000) // 1200 sec timeout

interface Results {
    new: number
    control: number
    diffMs: number
    diffMagnitude: number
}

const RUNS = 2000

const FUTURE_TIMESTAMP = '2050-10-14T11:42:06.502Z'
const PAST_TIMESTAMP = '2000-10-14T11:42:06.502Z'

function generateProperties(target: number): [Record<string, string>, Record<string, string>, Record<string, any>] {
    const startingProperties: Record<string, any> = {}
    const setProperties: Record<string, any> = {}
    const setOnceProperties: Record<string, any> = {}
    const propertiesLastUpdatedAt: Record<string, string> = {}
    const propertiesLastOperation: Record<string, string> = {}

    for (let i = 0; i < target; ++i) {
        const propName = `property_${i}`
        startingProperties[propName] = 'this is my initial value'
        if (i % 2 === 0) {
            setProperties[propName] = 'this is my updated value'
        } else {
            setOnceProperties[propName] = 'this is my updated value'
        }

        if (i % 3 === 0) {
            propertiesLastUpdatedAt[propName] = FUTURE_TIMESTAMP
        } else {
            propertiesLastUpdatedAt[propName] = PAST_TIMESTAMP
        }

        if (i % 4 === 0) {
            propertiesLastOperation[propName] = 'set'
        } else {
            propertiesLastOperation[propName] = 'set_once'
        }
    }

    return [startingProperties, setProperties, setOnceProperties]
}

async function runUpdateCycle(
    hub: Hub,
    teamId: number,
    startingProperties: Record<string, any>,
    setProperties: Record<string, any>,
    setOnceProperties: Record<string, any>,
    isControl = false
): Promise<number> {
    const uuid = new UUIDT().toString()
    const distinctId = String(Math.random() + Math.random())
    const person = await hub.db.createPerson(DateTime.now(), startingProperties, teamId, null, false, uuid, [
        distinctId,
    ])

    const startTime = performance.now()
    if (isControl) {
        await hub.db.updatePersonPropertiesOld(teamId, distinctId, setProperties, setOnceProperties)
    } else {
        await hub.db.updatePersonProperties(teamId, distinctId, setProperties, setOnceProperties, DateTime.now())
    }
    const endTime = performance.now()
    return endTime - startTime
}

describe('ingestion benchmarks', () => {
    let team: Team
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        await resetTestDatabase()
        ;[hub, closeHub] = await createHub()
        team = await getFirstTeam(hub)

        // warmup
        for (let i = 0; i < 5; ++i) {
            const [startingProperties, setProperties, setOnceProperties] = generateProperties(20)
            await runUpdateCycle(hub, team.id, startingProperties, setProperties, setOnceProperties)
            await runUpdateCycle(hub, team.id, startingProperties, setProperties, setOnceProperties, true)
        }
    })

    afterEach(async () => {
        await closeHub?.()
    })

    test('woop', async () => {
        const results: Record<number, Results> = {
            10: {
                control: 0,
                new: 0,
                diffMs: 0,
                diffMagnitude: 0,
            },
            20: {
                control: 0,
                new: 0,
                diffMs: 0,
                diffMagnitude: 0,
            },
            50: {
                control: 0,
                new: 0,
                diffMs: 0,
                diffMagnitude: 0,
            },
            100: {
                control: 0,
                new: 0,
                diffMs: 0,
                diffMagnitude: 0,
            },
        }

        for (const totalProperties of [10, 20, 50, 100]) {
            const [startingProperties, setProperties, setOnceProperties] = generateProperties(totalProperties)
            let totalTimeControl = 0
            for (let i = 0; i < RUNS; ++i) {
                const timeTaken = await runUpdateCycle(
                    hub,
                    team.id,
                    startingProperties,
                    setProperties,
                    setOnceProperties,
                    true
                )
                totalTimeControl += timeTaken
            }

            let totalTimeNew = 0
            for (let i = 0; i < RUNS; ++i) {
                const timeTaken = await runUpdateCycle(
                    hub,
                    team.id,
                    startingProperties,
                    setProperties,
                    setOnceProperties
                )
                totalTimeNew += timeTaken
            }

            const timePerRunControl = totalTimeControl / RUNS
            const timePerRunNew = totalTimeNew / RUNS

            results[totalProperties].control = Math.round(timePerRunControl * 100) / 100
            results[totalProperties].new = Math.round(timePerRunNew * 100) / 100
            results[totalProperties].diffMs = Math.round((timePerRunNew - timePerRunControl) * 100) / 100
            results[totalProperties].diffMagnitude = Math.round((timePerRunNew / timePerRunControl) * 100) / 100
        }

        console.table(results)
    })
})
