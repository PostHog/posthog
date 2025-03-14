import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { posthogFilterOutPlugin } from '../../../src/cdp/legacy-plugins/_transformations/posthog-filter-out-plugin/template'
import { template as defaultTemplate } from '../../../src/cdp/templates/_transformations/default/default.template'
import { template as geoipTemplate } from '../../../src/cdp/templates/_transformations/geoip/geoip.template'
import { compileHog } from '../../../src/cdp/templates/compiler'
import { getProducedKafkaMessages } from '../../../tests/helpers/mocks/producer.mock'
import { forSnapshot } from '../../../tests/helpers/snapshots'
import { getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { createHogFunction, insertHogFunction } from '../_tests/fixtures'
import { posthogPluginGeoip } from '../legacy-plugins/_transformations/posthog-plugin-geoip/template'
import { propertyFilterPlugin } from '../legacy-plugins/_transformations/property-filter-plugin/template'
import { HogFunctionTemplate } from '../templates/types'
import { HogTransformerService } from './hog-transformer.service'

jest.mock('../../utils/logger', () => ({
    status: {
        warn: jest.fn(),
        info: jest.fn(),
        debug: jest.fn(),
        error: jest.fn(),
    },
}))

const createPluginEvent = (event: Partial<PluginEvent> = {}, teamId: number = 1): PluginEvent => {
    return {
        ip: '12.87.118.0',
        site_url: 'http://localhost',
        team_id: teamId,
        now: '2024-06-07T12:00:00.000Z',
        uuid: 'event-id',
        event: 'event-name',
        distinct_id: 'distinct-id',
        properties: { $current_url: 'https://example.com', $ip: '12.87.118.0' },
        timestamp: '2024-01-01T00:00:00Z',
        ...event,
    }
}

describe('HogTransformer', () => {
    let hub: Hub
    let hogTransformer: HogTransformerService
    let teamId: number

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()

        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        // Create a team first before inserting hog functions
        const team = await getFirstTeam(hub)
        teamId = team.id

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
                id: 'd77e792e-0f35-431b-a983-097534aa4767',
            })
            await insertHogFunction(hub.db.postgres, teamId, geoIpFunction)

            // Start the transformer after inserting functions because it is
            // starting the hogfunction manager which updates the cache
            await hogTransformer['hogFunctionManager'].reloadAllHogFunctions()

            const event: PluginEvent = createPluginEvent({}, teamId)
            const result = await hogTransformer.transformEventAndProduceMessages(event)

            expect(result.event?.properties).toMatchInlineSnapshot(`
                {
                  "$current_url": "https://example.com",
                  "$geoip_accuracy_radius": 20,
                  "$geoip_city_name": "Cleveland",
                  "$geoip_continent_code": "NA",
                  "$geoip_continent_name": "North America",
                  "$geoip_country_code": "US",
                  "$geoip_country_name": "United States",
                  "$geoip_latitude": 41.5,
                  "$geoip_longitude": -81.6938,
                  "$geoip_postal_code": "44192",
                  "$geoip_subdivision_1_code": "OH",
                  "$geoip_subdivision_1_name": "Ohio",
                  "$geoip_time_zone": "America/New_York",
                  "$ip": "12.87.118.0",
                  "$set": {
                    "$geoip_accuracy_radius": 20,
                    "$geoip_city_confidence": null,
                    "$geoip_city_name": "Cleveland",
                    "$geoip_continent_code": "NA",
                    "$geoip_continent_name": "North America",
                    "$geoip_country_code": "US",
                    "$geoip_country_name": "United States",
                    "$geoip_latitude": 41.5,
                    "$geoip_longitude": -81.6938,
                    "$geoip_postal_code": "44192",
                    "$geoip_subdivision_1_code": "OH",
                    "$geoip_subdivision_1_name": "Ohio",
                    "$geoip_subdivision_2_code": null,
                    "$geoip_subdivision_2_name": null,
                    "$geoip_time_zone": "America/New_York",
                  },
                  "$set_once": {
                    "$initial_geoip_accuracy_radius": 20,
                    "$initial_geoip_city_confidence": null,
                    "$initial_geoip_city_name": "Cleveland",
                    "$initial_geoip_continent_code": "NA",
                    "$initial_geoip_continent_name": "North America",
                    "$initial_geoip_country_code": "US",
                    "$initial_geoip_country_name": "United States",
                    "$initial_geoip_latitude": 41.5,
                    "$initial_geoip_longitude": -81.6938,
                    "$initial_geoip_postal_code": "44192",
                    "$initial_geoip_subdivision_1_code": "OH",
                    "$initial_geoip_subdivision_1_name": "Ohio",
                    "$initial_geoip_subdivision_2_code": null,
                    "$initial_geoip_subdivision_2_name": null,
                    "$initial_geoip_time_zone": "America/New_York",
                  },
                  "$transformations_failed": [],
                  "$transformations_succeeded": [
                    "GeoIP (d77e792e-0f35-431b-a983-097534aa4767)",
                  ],
                }
            `)
        })

        it('only allow modifying certain properties', async () => {
            // Setup the hog function
            const fn = createHogFunction({
                type: 'transformation',
                name: 'Modifier',
                team_id: teamId,
                enabled: true,
                bytecode: [],
                execution_order: 1,
                id: 'd77e792e-0f35-431b-a983-097534aa4767',
                hog: `
                    let returnEvent := event
                    returnEvent.distinct_id := 'modified-distinct-id'
                    returnEvent.event := 'modified-event'
                    returnEvent.properties.test_property := 'modified-test-value'
                    returnEvent.something_else := 'should not be allowed'
                    returnEvent.timestamp := 'should not be allowed'
                    return returnEvent
                `,
            })
            fn.bytecode = await compileHog(fn.hog)
            await insertHogFunction(hub.db.postgres, teamId, fn)
            await hogTransformer['hogFunctionManager'].reloadAllHogFunctions()

            const event: PluginEvent = createPluginEvent({}, teamId)
            const result = await hogTransformer.transformEventAndProduceMessages(event)

            expect(result.event).toMatchInlineSnapshot(`
                {
                  "distinct_id": "modified-distinct-id",
                  "event": "modified-event",
                  "ip": "12.87.118.0",
                  "now": "2024-06-07T12:00:00.000Z",
                  "properties": {
                    "$current_url": "https://example.com",
                    "$ip": "12.87.118.0",
                    "$transformations_failed": [],
                    "$transformations_succeeded": [
                      "Modifier (d77e792e-0f35-431b-a983-097534aa4767)",
                    ],
                    "test_property": "modified-test-value",
                  },
                  "site_url": "http://localhost",
                  "team_id": 2,
                  "timestamp": "2024-01-01T00:00:00Z",
                  "uuid": "event-id",
                }
            `)
        })
        it('should execute multiple transformations and produce messages', async () => {
            const testTemplate: HogFunctionTemplate = {
                free: true,
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

            const result = await hogTransformer.transformEventAndProduceMessages(event)

            expect(executeHogFunctionSpy).toHaveBeenCalledTimes(3)
            expect(executeHogFunctionSpy.mock.calls[0][0]).toMatchObject({ execution_order: 1 })
            expect(executeHogFunctionSpy.mock.calls[1][0]).toMatchObject({ execution_order: 2 })
            expect(executeHogFunctionSpy.mock.calls[2][0]).toMatchObject({ execution_order: 3 })
            expect(event.properties?.test_property).toEqual('test_value')

            await Promise.all(result.messagePromises)

            const messages = getProducedKafkaMessages()
            // Replace certain messages that have changeable values
            messages.forEach((x) => {
                if (typeof x.value.message === 'string' && x.value.message.includes('Function completed in')) {
                    x.value.message = 'Function completed in [REPLACED]'
                }
            })
            expect(forSnapshot(messages)).toMatchSnapshot()
        })

        it('should delete a property from previous transformation', async () => {
            const addingTemplate: HogFunctionTemplate = {
                free: true,
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
                free: true,
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

            const result = await hogTransformer.transformEventAndProduceMessages(event)

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
                free: true,
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
                free: true,
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
                free: true,
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

            await hogTransformer.transformEventAndProduceMessages(event)
            expect(executeHogFunctionSpy).toHaveBeenCalledTimes(3)
            expect(executeHogFunctionSpy.mock.calls[0][0]).toMatchObject({ execution_order: 1 })
            expect(executeHogFunctionSpy.mock.calls[1][0]).toMatchObject({ execution_order: 2 })
            expect(executeHogFunctionSpy.mock.calls[2][0]).toMatchObject({ execution_order: null })
        })

        it('should track successful and failed transformations', async () => {
            // Create a successful transformation
            const successTemplate: HogFunctionTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-success',
                name: 'Success Template',
                description: 'A template that should succeed',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.success := true
                    return returnEvent
                `,
                inputs_schema: [],
            }

            // Create a failing transformation
            const failingTemplate: HogFunctionTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-fail',
                name: 'Failing Template',
                description: 'A template that should fail',
                category: ['Custom'],
                hog: `
                    // Return invalid result (not an object with properties)
                    return "invalid"
                `,
                inputs_schema: [],
            }

            const successByteCode = await compileHog(successTemplate.hog)
            const successFunction = createHogFunction({
                type: 'transformation',
                name: successTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: successByteCode,
                execution_order: 1,
            })

            const failByteCode = await compileHog(failingTemplate.hog)
            const failFunction = createHogFunction({
                type: 'transformation',
                name: failingTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: failByteCode,
                execution_order: 2,
            })

            await insertHogFunction(hub.db.postgres, teamId, successFunction)
            await insertHogFunction(hub.db.postgres, teamId, failFunction)

            await hogTransformer['hogFunctionManager'].reloadAllHogFunctions()

            const event = createPluginEvent(
                {
                    event: 'test',
                    properties: {},
                },
                teamId
            )

            const result = await hogTransformer.transformEventAndProduceMessages(event)

            // Verify the event has both success and failure tracking
            expect(result.event?.properties).toEqual({
                success: true, // From successful transformation
                $transformations_succeeded: [`Success Template (${successFunction.id})`],
                $transformations_failed: [`Failing Template (${failFunction.id})`],
            })
        })

        it('should not add transformation tracking properties if no transformations run', async () => {
            const event = createPluginEvent(
                {
                    event: 'test',
                    properties: { original: true },
                },
                teamId
            )

            const result = await hogTransformer.transformEventAndProduceMessages(event)

            // Verify the event properties are unchanged
            expect(result.event?.properties).toEqual({
                original: true,
            })
            expect(result.event?.properties).not.toHaveProperty('$transformations_succeeded')
            expect(result.event?.properties).not.toHaveProperty('$transformations_failed')
        })

        it('should preserve existing transformation results when adding new ones', async () => {
            const successTemplate: HogFunctionTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-success',
                name: 'Success Template',
                description: 'A template that should succeed',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.success := true
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const successByteCode = await compileHog(successTemplate.hog)
            const successFunction = createHogFunction({
                type: 'transformation',
                name: successTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: successByteCode,
                execution_order: 1,
            })

            await insertHogFunction(hub.db.postgres, teamId, successFunction)
            await hogTransformer['hogFunctionManager'].reloadAllHogFunctions()

            const event = createPluginEvent(
                {
                    event: 'test',
                    properties: {
                        $transformations_succeeded: ['Previous Success (prev-id)'],
                        $transformations_failed: ['Previous Failure (prev-id)'],
                    },
                },
                teamId
            )

            const result = await hogTransformer.transformEventAndProduceMessages(event)

            // Verify new results are appended to existing ones
            expect(result?.event?.properties?.$transformations_succeeded).toEqual([
                'Previous Success (prev-id)',
                `Success Template (${successFunction.id})`,
            ])
            expect(result?.event?.properties?.$transformations_failed).toEqual(['Previous Failure (prev-id)'])
        })
    })

    describe('legacy plugins', () => {
        let executeSpy: jest.SpyInstance

        beforeEach(async () => {
            const filterOutPlugin = createHogFunction({
                type: 'transformation',
                name: posthogFilterOutPlugin.template.name,
                template_id: 'plugin-posthog-filter-out-plugin',
                inputs: {
                    eventsToDrop: {
                        value: 'drop-me',
                    },
                },
                team_id: teamId,
                enabled: true,
                hog: posthogFilterOutPlugin.template.hog,
                inputs_schema: posthogFilterOutPlugin.template.inputs_schema,
                id: 'c342e9ae-9f76-4379-a465-d33b4826bc05',
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
            const result = await hogTransformer.transformEventAndProduceMessages(event)
            expect(executeSpy).toHaveBeenCalledTimes(1)
            expect(result.event).toMatchInlineSnapshot(`null`)
        })

        it('handles legacy plugin transformation to keep events', async () => {
            const event: PluginEvent = createPluginEvent({ event: 'keep-me', team_id: teamId })
            const result = await hogTransformer.transformEventAndProduceMessages(event)

            expect(executeSpy).toHaveBeenCalledTimes(1)
            expect(result.event).toMatchInlineSnapshot(`
                {
                  "distinct_id": "distinct-id",
                  "event": "keep-me",
                  "ip": "12.87.118.0",
                  "now": "2024-06-07T12:00:00.000Z",
                  "properties": {
                    "$current_url": "https://example.com",
                    "$ip": "12.87.118.0",
                    "$transformations_failed": [],
                    "$transformations_succeeded": [
                      "Filter Out Plugin (c342e9ae-9f76-4379-a465-d33b4826bc05)",
                    ],
                  },
                  "site_url": "http://localhost",
                  "team_id": 2,
                  "timestamp": "2024-01-01T00:00:00Z",
                  "uuid": "event-id",
                }
            `)
        })
    })

    describe('long event chain', () => {
        it('should handle a long chain of transformations', async () => {
            const geoIp = createHogFunction({
                type: 'transformation',
                name: posthogPluginGeoip.template.name,
                template_id: posthogPluginGeoip.template.id,
                inputs: {},
                team_id: teamId,
                enabled: true,
                hog: posthogPluginGeoip.template.hog,
                inputs_schema: posthogPluginGeoip.template.inputs_schema,
            })

            const filterPlugin = createHogFunction({
                type: 'transformation',
                name: propertyFilterPlugin.template.name,
                template_id: propertyFilterPlugin.template.id,
                inputs: {
                    properties: {
                        value: '$ip,$geoip_country_code,$geoip_latitude,$geoip_longitude',
                    },
                },
                team_id: teamId,
                enabled: true,
                hog: propertyFilterPlugin.template.hog,
                inputs_schema: propertyFilterPlugin.template.inputs_schema,
            })

            await insertHogFunction(hub.db.postgres, teamId, geoIp)
            await insertHogFunction(hub.db.postgres, teamId, filterPlugin)
            await hogTransformer['hogFunctionManager'].reloadAllHogFunctions()

            const event: PluginEvent = createPluginEvent({ event: 'keep-me', team_id: teamId })
            const result = await hogTransformer.transformEventAndProduceMessages(event)

            expect(forSnapshot(result.event)).toMatchInlineSnapshot(`
                {
                  "distinct_id": "distinct-id",
                  "event": "keep-me",
                  "ip": null,
                  "now": "2024-06-07T12:00:00.000Z",
                  "properties": {
                    "$current_url": "https://example.com",
                    "$geoip_accuracy_radius": 20,
                    "$geoip_city_name": "Cleveland",
                    "$geoip_continent_code": "NA",
                    "$geoip_continent_name": "North America",
                    "$geoip_country_name": "United States",
                    "$geoip_postal_code": "44192",
                    "$geoip_subdivision_1_code": "OH",
                    "$geoip_subdivision_1_name": "Ohio",
                    "$geoip_time_zone": "America/New_York",
                    "$set": {
                      "$geoip_accuracy_radius": 20,
                      "$geoip_city_confidence": null,
                      "$geoip_city_name": "Cleveland",
                      "$geoip_continent_code": "NA",
                      "$geoip_continent_name": "North America",
                      "$geoip_country_code": "US",
                      "$geoip_country_name": "United States",
                      "$geoip_latitude": 41.5,
                      "$geoip_longitude": -81.6938,
                      "$geoip_postal_code": "44192",
                      "$geoip_subdivision_1_code": "OH",
                      "$geoip_subdivision_1_name": "Ohio",
                      "$geoip_subdivision_2_code": null,
                      "$geoip_subdivision_2_name": null,
                      "$geoip_time_zone": "America/New_York",
                    },
                    "$set_once": {
                      "$initial_geoip_accuracy_radius": 20,
                      "$initial_geoip_city_confidence": null,
                      "$initial_geoip_city_name": "Cleveland",
                      "$initial_geoip_continent_code": "NA",
                      "$initial_geoip_continent_name": "North America",
                      "$initial_geoip_country_code": "US",
                      "$initial_geoip_country_name": "United States",
                      "$initial_geoip_latitude": 41.5,
                      "$initial_geoip_longitude": -81.6938,
                      "$initial_geoip_postal_code": "44192",
                      "$initial_geoip_subdivision_1_code": "OH",
                      "$initial_geoip_subdivision_1_name": "Ohio",
                      "$initial_geoip_subdivision_2_code": null,
                      "$initial_geoip_subdivision_2_name": null,
                      "$initial_geoip_time_zone": "America/New_York",
                    },
                    "$transformations_failed": [],
                    "$transformations_succeeded": [
                      "GeoIP (<REPLACED-UUID-0>)",
                      "Property Filter (<REPLACED-UUID-1>)",
                    ],
                  },
                  "site_url": "http://localhost",
                  "team_id": 2,
                  "timestamp": "2024-01-01T00:00:00Z",
                  "uuid": "event-id",
                }
            `)
        })
    })
})
