import { Reader } from '@maxmind/geoip2-node'
import { PluginEvent } from '@posthog/plugin-scaffold'
import { readFileSync } from 'fs'
import { join } from 'path'
import { brotliDecompressSync } from 'zlib'

import { template as filterOutPluginTemplate } from '../../../src/cdp/legacy-plugins/_transformations/posthog-filter-out-plugin/template'
import { template as defaultTemplate } from '../../../src/cdp/templates/_transformations/default/default.template'
import { template as geoipTemplate } from '../../../src/cdp/templates/_transformations/geoip/geoip.template'
import { compileHog } from '../../../src/cdp/templates/compiler'
import { createHogFunction, insertHogFunction } from '../../../tests/cdp/fixtures'
import { createTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { HogFunctionTemplate } from '../templates/types'
import { HogTransformerService } from './hog-transformer.service'

jest.mock('../../utils/status', () => ({
    status: {
        warn: jest.fn(),
        info: jest.fn(),
        debug: jest.fn(),
        updatePrompt: jest.fn(),
    },
}))

const createPluginEvent = (event: Partial<PluginEvent> = {}, teamId: number = 1): PluginEvent => {
    return {
        ip: '89.160.20.129',
        site_url: 'http://localhost',
        team_id: teamId,
        now: '2024-06-07T12:00:00.000Z',
        uuid: 'event-id',
        event: 'event-name',
        distinct_id: 'distinct-id',
        properties: { $current_url: 'https://example.com', $ip: '89.160.20.129' },
        timestamp: '2024-01-01T00:00:00Z',
        ...event,
    }
}

describe('HogTransformer', () => {
    let hub: Hub
    let hogTransformer: HogTransformerService
    let teamId: number

    const mmdbBrotliContents = readFileSync(join(__dirname, '../../../tests/assets/GeoLite2-City-Test.mmdb.br'))

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()

        // Create a team first before inserting hog functions
        const team = await hub.db.fetchTeam(2)
        teamId = await createTeam(hub.db.postgres, team!.organization_id)

        hub.mmdb = Reader.openBuffer(brotliDecompressSync(mmdbBrotliContents))
        hogTransformer = new HogTransformerService(hub)
        await hogTransformer.start()
    })

    afterEach(async () => {
        await closeHub(hub)
        await hogTransformer.stop()

        jest.spyOn(hogTransformer['pluginExecutor'], 'execute')
    })

    describe('transformEvent', () => {
        it('handles geoip lookup transformation', async () => {
            // Setup the hog function
            const hogByteCode = await compileHog(geoipTemplate.hog)
            const geoIpFunction = createHogFunction({
                type: 'transformation',
                name: geoipTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: hogByteCode,
                execution_order: 1,
            })
            await insertHogFunction(hub.db.postgres, teamId, geoIpFunction)

            // Start the transformer after inserting functions because it is
            // starting the hogfunction manager which updates the cache
            await hogTransformer['hogFunctionManager'].reloadAllHogFunctions()

            const event: PluginEvent = createPluginEvent({}, teamId)
            const result = await hogTransformer.transformEvent(event)

            expect(result.event?.properties).toMatchInlineSnapshot(`
                {
                  "$current_url": "https://example.com",
                  "$geoip_accuracy_radius": 76,
                  "$geoip_city_name": "Linköping",
                  "$geoip_continent_code": "EU",
                  "$geoip_continent_name": "Europe",
                  "$geoip_country_code": "SE",
                  "$geoip_country_name": "Sweden",
                  "$geoip_latitude": 58.4167,
                  "$geoip_longitude": 15.6167,
                  "$geoip_subdivision_1_code": "E",
                  "$geoip_subdivision_1_name": "Östergötland County",
                  "$geoip_time_zone": "Europe/Stockholm",
                  "$ip": "89.160.20.129",
                  "$set": {
                    "$geoip_accuracy_radius": 76,
                    "$geoip_city_confidence": null,
                    "$geoip_city_name": "Linköping",
                    "$geoip_continent_code": "EU",
                    "$geoip_continent_name": "Europe",
                    "$geoip_country_code": "SE",
                    "$geoip_country_name": "Sweden",
                    "$geoip_latitude": 58.4167,
                    "$geoip_longitude": 15.6167,
                    "$geoip_postal_code": null,
                    "$geoip_subdivision_1_code": "E",
                    "$geoip_subdivision_1_name": "Östergötland County",
                    "$geoip_subdivision_2_code": null,
                    "$geoip_subdivision_2_name": null,
                    "$geoip_time_zone": "Europe/Stockholm",
                  },
                  "$set_once": {
                    "$initial_geoip_accuracy_radius": 76,
                    "$initial_geoip_city_confidence": null,
                    "$initial_geoip_city_name": "Linköping",
                    "$initial_geoip_continent_code": "EU",
                    "$initial_geoip_continent_name": "Europe",
                    "$initial_geoip_country_code": "SE",
                    "$initial_geoip_country_name": "Sweden",
                    "$initial_geoip_latitude": 58.4167,
                    "$initial_geoip_longitude": 15.6167,
                    "$initial_geoip_postal_code": null,
                    "$initial_geoip_subdivision_1_code": "E",
                    "$initial_geoip_subdivision_1_name": "Östergötland County",
                    "$initial_geoip_subdivision_2_code": null,
                    "$initial_geoip_subdivision_2_name": null,
                    "$initial_geoip_time_zone": "Europe/Stockholm",
                  },
                }
            `)
        })
        it('should execute multiple transformations', async () => {
            const testTemplate: HogFunctionTemplate = {
                status: 'beta',
                type: 'transformation',
                id: 'template-test',
                name: 'Test Template',
                description: 'A simple test template that adds a test property',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.test_property := 'test_value'
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const geoTransformationIpByteCode = await compileHog(geoipTemplate.hog)
            const geoIpTransformationFunction = createHogFunction({
                type: 'transformation',
                name: geoipTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: geoTransformationIpByteCode,
                execution_order: 1,
            })

            const defaultTransformationByteCode = await compileHog(defaultTemplate.hog)
            const defaultTransformationFunction = createHogFunction({
                type: 'transformation',
                name: defaultTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: defaultTransformationByteCode,
                execution_order: 2,
            })

            const testTransformationByteCode = await compileHog(testTemplate.hog)
            const testTransformationFunction = createHogFunction({
                type: 'transformation',
                name: testTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: testTransformationByteCode,
                execution_order: 3,
            })

            await insertHogFunction(hub.db.postgres, teamId, testTransformationFunction)
            await insertHogFunction(hub.db.postgres, teamId, defaultTransformationFunction)
            await insertHogFunction(hub.db.postgres, teamId, geoIpTransformationFunction)

            await hogTransformer['hogFunctionManager'].reloadAllHogFunctions()

            const executeHogFunctionSpy = jest.spyOn(hogTransformer as any, 'executeHogFunction')

            const event: PluginEvent = {
                ip: '89.160.20.129',
                site_url: 'http://localhost',
                team_id: teamId,
                now: '2024-06-07T12:00:00.000Z',
                uuid: 'event-id',
                event: 'event-name',
                distinct_id: 'distinct-id',
                properties: { $ip: '89.160.20.129' },
                timestamp: '2024-01-01T00:00:00Z',
            }

            await hogTransformer.transformEvent(event)

            expect(executeHogFunctionSpy).toHaveBeenCalledTimes(3)
            expect(executeHogFunctionSpy.mock.calls[0][0]).toMatchObject({ execution_order: 1 })
            expect(executeHogFunctionSpy.mock.calls[1][0]).toMatchObject({ execution_order: 2 })
            expect(executeHogFunctionSpy.mock.calls[2][0]).toMatchObject({ execution_order: 3 })
            expect(event.properties?.test_property).toEqual('test_value')
        })

        it('should delete a property from previous transformation', async () => {
            const addingTemplate: HogFunctionTemplate = {
                status: 'alpha',
                type: 'transformation',
                id: 'template-test',
                name: 'Test Template',
                description: 'A simple test template that adds a test property',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.test_property := 'test_value'
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const deletingTemplate: HogFunctionTemplate = {
                status: 'alpha',
                type: 'transformation',
                id: 'template-test',
                name: 'Test Template',
                description: 'A simple test template that adds a test property',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.test_property := null
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const addingTransformationByteCode = await compileHog(addingTemplate.hog)
            const addingTransformationFunction = createHogFunction({
                type: 'transformation',
                name: addingTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: addingTransformationByteCode,
                execution_order: 1,
            })

            const deletingTransformationByteCode = await compileHog(deletingTemplate.hog)
            const deletingTransformationFunction = createHogFunction({
                type: 'transformation',
                name: deletingTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: deletingTransformationByteCode,
                execution_order: 2,
            })

            await insertHogFunction(hub.db.postgres, teamId, deletingTransformationFunction)
            await insertHogFunction(hub.db.postgres, teamId, addingTransformationFunction)

            await hogTransformer['hogFunctionManager'].reloadAllHogFunctions()

            const executeHogFunctionSpy = jest.spyOn(hogTransformer as any, 'executeHogFunction')

            const event: PluginEvent = {
                ip: '89.160.20.129',
                site_url: 'http://localhost',
                team_id: teamId,
                now: '2024-06-07T12:00:00.000Z',
                uuid: 'event-id',
                event: 'event-name',
                distinct_id: 'distinct-id',
                properties: { $ip: '89.160.20.129' },
                timestamp: '2024-01-01T00:00:00Z',
            }

            const result = await hogTransformer.transformEvent(event)

            /*
             * First call is the adding the test property
             * Second call is the deleting the test property
             * hence the result is null
             */
            expect(executeHogFunctionSpy).toHaveBeenCalledTimes(2)
            expect(result?.event?.properties?.test_property).toEqual(null)
        })
        it('should execute tranformation without execution_order last', async () => {
            const firstTemplate: HogFunctionTemplate = {
                status: 'alpha',
                type: 'transformation',
                id: 'template-test',
                name: 'Test Template',
                description: 'A simple test template that adds a test property',
                category: ['Custom'],
                hog: `
                    return event
                `,
                inputs_schema: [],
            }

            const secondTemplate: HogFunctionTemplate = {
                status: 'alpha',
                type: 'transformation',
                id: 'template-test',
                name: 'Test Template',
                description: 'A simple test template that adds a test property',
                category: ['Custom'],
                hog: `
                    return event
                `,
                inputs_schema: [],
            }

            const thirdTemplate: HogFunctionTemplate = {
                status: 'alpha',
                type: 'transformation',
                id: 'template-test',
                name: 'Test Template',
                description: 'A simple test template that adds a test property',
                category: ['Custom'],
                hog: `
                    return event
                `,
                inputs_schema: [],
            }

            const firstTransformationByteCode = await compileHog(firstTemplate.hog)
            const firstTransformationFunction = createHogFunction({
                type: 'transformation',
                name: firstTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: firstTransformationByteCode,
                execution_order: 1,
            })

            const secondTransformationByteCode = await compileHog(secondTemplate.hog)
            const secondTransformationFunction = createHogFunction({
                type: 'transformation',
                name: secondTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: secondTransformationByteCode,
                execution_order: 2,
            })

            const thirdTransformationByteCode = await compileHog(thirdTemplate.hog)
            const thirdTransformationFunction = createHogFunction({
                type: 'transformation',
                name: thirdTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: thirdTransformationByteCode,
                execution_order: undefined,
            })

            await insertHogFunction(hub.db.postgres, teamId, thirdTransformationFunction)
            await insertHogFunction(hub.db.postgres, teamId, secondTransformationFunction)
            await insertHogFunction(hub.db.postgres, teamId, firstTransformationFunction)
            await hogTransformer['hogFunctionManager'].reloadAllHogFunctions()

            const executeHogFunctionSpy = jest.spyOn(hogTransformer as any, 'executeHogFunction')

            const event: PluginEvent = {
                ip: '89.160.20.129',
                site_url: 'http://localhost',
                team_id: teamId,
                now: '2024-06-07T12:00:00.000Z',
                uuid: 'event-id',
                event: 'event-name',
                distinct_id: 'distinct-id',
                properties: { $ip: '89.160.20.129' },
                timestamp: '2024-01-01T00:00:00Z',
            }

            await hogTransformer.transformEvent(event)
            expect(executeHogFunctionSpy).toHaveBeenCalledTimes(3)
            expect(executeHogFunctionSpy.mock.calls[0][0]).toMatchObject({ execution_order: 1 })
            expect(executeHogFunctionSpy.mock.calls[1][0]).toMatchObject({ execution_order: 2 })
            expect(executeHogFunctionSpy.mock.calls[2][0]).toMatchObject({ execution_order: null })
        })
    })

    describe('legacy plugins', () => {
        let executeSpy: jest.SpyInstance

        beforeEach(async () => {
            const filterOutPlugin = createHogFunction({
                type: 'transformation',
                name: filterOutPluginTemplate.name,
                template_id: 'plugin-posthog-filter-out-plugin',
                inputs: {
                    eventsToDrop: {
                        value: 'drop-me',
                    },
                },
                team_id: teamId,
                enabled: true,
                hog: filterOutPluginTemplate.hog,
                inputs_schema: filterOutPluginTemplate.inputs_schema,
            })

            await insertHogFunction(hub.db.postgres, teamId, filterOutPlugin)
            await hogTransformer['hogFunctionManager'].reloadAllHogFunctions()

            // Set up the spy after hogTransformer is initialized
            executeSpy = jest.spyOn(hogTransformer['pluginExecutor'], 'execute')
        })

        afterEach(() => {
            executeSpy.mockRestore()
        })

        it('handles legacy plugin transformation to drop events', async () => {
            const event: PluginEvent = createPluginEvent({ event: 'drop-me', team_id: teamId })
            const result = await hogTransformer.transformEvent(event)
            expect(executeSpy).toHaveBeenCalledTimes(1)
            expect(result).toMatchInlineSnapshot(`
                {
                  "event": null,
                  "messagePromises": [
                    Promise {},
                    Promise {},
                  ],
                }
            `)
        })

        it('handles legacy plugin transformation to keep events', async () => {
            const event: PluginEvent = createPluginEvent({ event: 'keep-me', team_id: teamId })
            const result = await hogTransformer.transformEvent(event)

            expect(executeSpy).toHaveBeenCalledTimes(1)
            expect(result).toMatchInlineSnapshot(`
                {
                  "event": {
                    "distinct_id": "distinct-id",
                    "event": "keep-me",
                    "ip": "89.160.20.129",
                    "now": "2024-06-07T12:00:00.000Z",
                    "properties": {
                      "$current_url": "https://example.com",
                      "$ip": "89.160.20.129",
                    },
                    "site_url": "http://localhost",
                    "team_id": ${teamId},
                    "timestamp": "2024-01-01T00:00:00Z",
                    "uuid": "event-id",
                  },
                  "messagePromises": [
                    Promise {},
                    Promise {},
                  ],
                }
            `)
        })
    })
})
