import { Reader } from '@maxmind/geoip2-node'
import { PluginEvent } from '@posthog/plugin-scaffold'
import { readFileSync } from 'fs'
import { join } from 'path'
import { brotliDecompressSync } from 'zlib'

import { template as defaultTemplate } from '../../../src/cdp/templates/_transformations/default/default.template'
import { template as filterOutPluginTemplate } from '~/src/cdp/legacy-plugins/_transformations/posthog-filter-out-plugin/template'
import { template as geoipTemplate } from '../../../src/cdp/templates/_transformations/geoip/geoip.template'
import { compileHog } from '../../../src/cdp/templates/compiler'
import { createHogFunction, insertHogFunction } from '../../../tests/cdp/fixtures'
import { resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { HogFunctionTemplate } from '../templates/types'
import { HogTransformerService } from './hog-transformer.service'
let mockGetTeamHogFunctions: jest.Mock

jest.mock('../../utils/status', () => ({
    status: {
        warn: jest.fn(),
        info: jest.fn(),
        debug: jest.fn(),
        updatePrompt: jest.fn(),
    },
}))

jest.mock('../../cdp/services/hog-function-manager.service', () => ({
    HogFunctionManagerService: jest.fn().mockImplementation(() => ({
        getTeamHogFunctions: (mockGetTeamHogFunctions = jest.fn().mockReturnValue([])),
    })),
}))

const createPluginEvent = (event: Partial<PluginEvent> = {}): PluginEvent => {
    return {
        ip: '89.160.20.129',
        site_url: 'http://localhost',
        team_id: 1,
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

    const mmdbBrotliContents = readFileSync(join(__dirname, '../../../tests/assets/GeoLite2-City-Test.mmdb.br'))

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()

        hub.mmdb = Reader.openBuffer(brotliDecompressSync(mmdbBrotliContents))
        hogTransformer = new HogTransformerService(hub)
        await hogTransformer.start()
    })

    afterEach(async () => {
        await closeHub(hub)

        jest.spyOn(hogTransformer['pluginExecutor'], 'execute')
    })

    describe('transformEvent', () => {
        it('handles geoip lookup transformation', async () => {
            jest.useFakeTimers()
            jest.setSystemTime(new Date('2024-06-07T12:00:00.000Z'))

            const hogByteCode = await compileHog(geoipTemplate.hog)
            const geoIpFunction = createHogFunction({
                ...geoipTemplate,
                bytecode: hogByteCode,
                execution_order: 1,
            })

            await insertHogFunction(hub.postgres, 1, geoIpFunction)

            const event: PluginEvent = createPluginEvent()
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
    })

    describe('legacy plugins', () => {
        beforeEach(() => {
            const filterOutPlugin = createHogFunction({
                ...filterOutPluginTemplate,
                type: 'transformation',
                template_id: 'plugin-posthog-filter-out-plugin',
                inputs: {
                    eventsToDrop: {
                        value: 'drop-me',
                    },
                },
            })

            mockGetTeamHogFunctions.mockReturnValue([filterOutPlugin])
        })

        it('handles legacy plugin transformation to drop events', async () => {
            const event: PluginEvent = createPluginEvent({ event: 'drop-me' })
            const result = await hogTransformer.transformEvent(event)
            expect(hogTransformer['pluginExecutor'].execute).toHaveBeenCalledTimes(1)
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

        it('handles legacy plugin transformation to drop events', async () => {
            const event: PluginEvent = createPluginEvent({ event: 'keep-me' })
            const result = await hogTransformer.transformEvent(event)

            expect(hogTransformer['pluginExecutor'].execute).toHaveBeenCalledTimes(1)
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
                    "team_id": 1,
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

        it('should execute multiple transformations in execution order', async () => {
            const testTemplate: HogFunctionTemplate = {
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

            const geoTransformationIpByteCode = await compileHog(geoipTemplate.hog)
            const geoIpTransformationFunction = createHogFunction({
                ...geoipTemplate,
                bytecode: geoTransformationIpByteCode,
                execution_order: 1,
            })

            const defaultTransformationByteCode = await compileHog(defaultTemplate.hog)
            const defaultTransformationFunction = createHogFunction({
                ...defaultTemplate,
                bytecode: defaultTransformationByteCode,
                execution_order: 2,
            })

            const testTransformationByteCode = await compileHog(testTemplate.hog)
            const testTransformationFunction = createHogFunction({
                ...testTemplate,
                bytecode: testTransformationByteCode,
                execution_order: 3,
            })

            await insertHogFunction(hub.postgres, 1, defaultTransformationFunction)
            await insertHogFunction(hub.postgres, 1, geoIpTransformationFunction)
            await insertHogFunction(hub.postgres, 1, testTransformationFunction)

            const createHogFunctionInvocationSpy = jest.spyOn(hogTransformer as any, 'createHogFunctionInvocation')

            const event: PluginEvent = {
                ip: '89.160.20.129',
                site_url: 'http://localhost',
                team_id: 1,
                now: '2024-06-07T12:00:00.000Z',
                uuid: 'event-id',
                event: 'event-name',
                distinct_id: 'distinct-id',
                properties: { $ip: '89.160.20.129' },
                timestamp: '2024-01-01T00:00:00Z',
            }

            await hogTransformer.transformEvent(event)

            expect(createHogFunctionInvocationSpy).toHaveBeenCalledTimes(3)
            expect(createHogFunctionInvocationSpy).toHaveBeenNthCalledWith(1, event, geoIpTransformationFunction)
            expect(createHogFunctionInvocationSpy).toHaveBeenNthCalledWith(2, event, defaultTransformationFunction)
            expect(createHogFunctionInvocationSpy).toHaveBeenNthCalledWith(3, event, testTransformationFunction)

            expect(event.properties?.test_property).toEqual('test_value')
            expect(event.properties?.$geoip_city_name).toEqual('Linköping')
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
                ...addingTemplate,
                bytecode: addingTransformationByteCode,
                execution_order: 1,
            })

            const deletingTransformationByteCode = await compileHog(deletingTemplate.hog)
            const deletingTransformationFunction = createHogFunction({
                ...deletingTemplate,
                bytecode: deletingTransformationByteCode,
                execution_order: 2,
            })

            await insertHogFunction(hub.postgres, 1, addingTransformationFunction)
            await insertHogFunction(hub.postgres, 1, deletingTransformationFunction)

            const createHogFunctionInvocationSpy = jest.spyOn(hogTransformer as any, 'createHogFunctionInvocation')

            const event: PluginEvent = {
                ip: '89.160.20.129',
                site_url: 'http://localhost',
                team_id: 1,
                now: '2024-06-07T12:00:00.000Z',
                uuid: 'event-id',
                event: 'event-name',
                distinct_id: 'distinct-id',
                properties: { $ip: '89.160.20.129' },
                timestamp: '2024-01-01T00:00:00Z',
            }

            await hogTransformer.transformEvent(event)

            expect(createHogFunctionInvocationSpy).toHaveBeenCalledTimes(2)
            expect(createHogFunctionInvocationSpy).toHaveBeenNthCalledWith(1, event, addingTransformationFunction)
            expect(createHogFunctionInvocationSpy).toHaveBeenNthCalledWith(2, event, deletingTransformationFunction)
            expect(event.properties?.test_property).toEqual(null)
        })
    })
})
