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
import { logger } from '../../utils/logger'
import { createHogFunction, insertHogFunction } from '../_tests/fixtures'
import { posthogPluginGeoip } from '../legacy-plugins/_transformations/posthog-plugin-geoip/template'
import { propertyFilterPlugin } from '../legacy-plugins/_transformations/property-filter-plugin/template'
import { HogWatcherState } from '../services/hog-watcher.service'
import { HogFunctionTemplate } from '../templates/types'
import { HogTransformerService } from './hog-transformer.service'

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
    })

    afterEach(async () => {
        await closeHub(hub)

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
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [geoIpFunction.id])

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
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [fn.id])

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

            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [
                testTransformationFunction.id,
                defaultTransformationFunction.id,
                geoIpTransformationFunction.id,
            ])

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

            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [
                addingTransformationFunction.id,
                deletingTransformationFunction.id,
            ])

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
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [
                thirdTransformationFunction.id,
                secondTransformationFunction.id,
                firstTransformationFunction.id,
            ])

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

            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [
                successFunction.id,
                failFunction.id,
            ])

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
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [successFunction.id])

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

        it('should track skipped transformations when filter does not match', async () => {
            const filterTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-test',
                name: 'Filter Template',
                description: 'A template that should be skipped when filter does not match',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.should_not_be_set := true
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const hogFunction = createHogFunction({
                type: 'transformation',
                name: filterTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(filterTemplate.hog),
                filters: {
                    bytecode: await compileHog(`
                        return event = 'match-me'
                    `),
                },
            })

            await insertHogFunction(hub.db.postgres, teamId, hogFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [hogFunction.id])

            const event = createPluginEvent(
                {
                    event: 'does-not-match-me',
                    properties: {
                        original: true,
                        $transformations_skipped: ['Previous Skip (prev-id)'],
                    },
                },
                teamId
            )

            const result = await hogTransformer.transformEventAndProduceMessages(event)

            // Verify transformation was skipped and tracked
            expect(result.event?.properties?.should_not_be_set).toBeUndefined()
            expect(result.event?.properties?.$transformations_skipped).toEqual([
                'Previous Skip (prev-id)',
                `${hogFunction.name} (${hogFunction.id})`,
            ])
            expect(result.event?.properties?.original).toBe(true)
            expect(result.event?.properties?.$transformations_succeeded).toBeUndefined()
            expect(result.event?.properties?.$transformations_failed).toBeUndefined()
        })

        it('should track both successful and skipped transformations in sequence', async () => {
            const successTemplate = {
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

            const skippedTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-skipped',
                name: 'Skipped Template',
                description: 'A template that should be skipped',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.should_not_be_set := true
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const successFunction = createHogFunction({
                type: 'transformation',
                name: successTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(successTemplate.hog),
                execution_order: 1,
            })

            const skippedFunction = createHogFunction({
                type: 'transformation',
                name: skippedTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(skippedTemplate.hog),
                execution_order: 2,
                filters: {
                    bytecode: await compileHog(`
                        return event = 'match-me'
                    `),
                },
            })

            await insertHogFunction(hub.db.postgres, teamId, successFunction)
            await insertHogFunction(hub.db.postgres, teamId, skippedFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [
                successFunction.id,
                skippedFunction.id,
            ])

            const event = createPluginEvent({ event: 'does-not-match' }, teamId)
            const result = await hogTransformer.transformEventAndProduceMessages(event)

            // Verify first transformation succeeded and second was skipped
            expect(result.event?.properties).toEqual({
                success: true,
                $current_url: 'https://example.com',
                $ip: '12.87.118.0',
                $transformations_succeeded: [`Success Template (${successFunction.id})`],
                $transformations_skipped: [`Skipped Template (${skippedFunction.id})`],
            })
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
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [filterOutPlugin.id])

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
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [geoIp.id, filterPlugin.id])

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

    describe('filter-based transformations', () => {
        beforeEach(() => {
            // Enable filter transformations for these tests
            hub.FILTER_TRANSFORMATIONS_ENABLED_TEAMS = [1, 2]
        })

        it('should skip transformation when filter does not match', async () => {
            const filterTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-test',
                name: 'Filter Template',
                description: 'A template that should be skipped when filter does not match',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.should_not_be_set := true
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const hogFunction = createHogFunction({
                type: 'transformation',
                name: filterTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(filterTemplate.hog),
                filters: {
                    bytecode: await compileHog(`
                        return event = 'match-me'
                    `),
                },
            })

            await insertHogFunction(hub.db.postgres, teamId, hogFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [hogFunction.id])

            const event = createPluginEvent({ event: 'does-not-match-me' }, teamId)
            const result = await hogTransformer.transformEventAndProduceMessages(event)

            // Verify transformation was skipped
            expect(result.event?.properties?.should_not_be_set).toBeUndefined()
            expect(result.event?.properties?.$transformations_succeeded).toBeUndefined()
            expect(result.event?.properties?.$transformations_failed).toBeUndefined()
            expect(result.event?.properties?.$transformations_skipped).toEqual([
                `${hogFunction.name} (${hogFunction.id})`,
            ])
        })

        it('should apply transformation when filter matches', async () => {
            const filterMatchingTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-test',
                name: 'Test Template',
                description: 'A template that adds a property when filter matches',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.test_property := 'test_value'
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const hogFunction = createHogFunction({
                type: 'transformation',
                name: filterMatchingTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(filterMatchingTemplate.hog),
                filters: {
                    bytecode: await compileHog(`
                        // Filter that matches events with event name 'match-me'
                        return event = 'match-me'
                    `),
                },
            })

            await insertHogFunction(hub.db.postgres, teamId, hogFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [hogFunction.id])

            // Test event that should match the filter
            const matchingEvent = createPluginEvent({ event: 'match-me' }, teamId)
            const matchResult = await hogTransformer.transformEventAndProduceMessages(matchingEvent)

            // Verify transformation was applied
            expect(matchResult.event?.properties?.test_property).toBe('test_value')
            expect(matchResult.event?.properties?.$transformations_succeeded).toContain(
                `${hogFunction.name} (${hogFunction.id})`
            )

            // Test event that shouldn't match the filter
            const nonMatchingEvent = createPluginEvent({ event: 'dont-match-me' }, teamId)
            const nonMatchResult = await hogTransformer.transformEventAndProduceMessages(nonMatchingEvent)

            // Verify transformation was skipped
            expect(nonMatchResult.event?.properties?.test_property).toBeUndefined()
            expect(nonMatchResult.event?.properties?.$transformations_succeeded).toBeUndefined()
            expect(nonMatchResult.event?.properties?.$transformations_failed).toBeUndefined()
            expect(nonMatchResult.event?.properties?.$transformations_skipped).toEqual([
                `${hogFunction.name} (${hogFunction.id})`,
            ])
        })

        it('should apply transformation when no filters are defined', async () => {
            const noFilterTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-test',
                name: 'No Filter Template',
                description: 'A template without filters',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.no_filter_property := 'applied'
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const hogFunction = createHogFunction({
                type: 'transformation',
                name: noFilterTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(noFilterTemplate.hog),
                // No filters defined
            })

            await insertHogFunction(hub.db.postgres, teamId, hogFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [hogFunction.id])

            const event = createPluginEvent({ event: 'any-event' }, teamId)
            const result = await hogTransformer.transformEventAndProduceMessages(event)

            // Verify transformation was applied
            expect(result.event?.properties?.no_filter_property).toBe('applied')
            expect(result.event?.properties?.$transformations_succeeded).toContain(
                `${hogFunction.name} (${hogFunction.id})`
            )
        })

        it('should apply transformation when filter errors and continue processing', async () => {
            const errorFilterTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-test',
                name: 'Error Filter Template',
                description: 'A template with an erroring filter',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.error_filter_property := 'should_be_set'
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const workingTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-working',
                name: 'Working Template',
                description: 'A template that should work',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.working_property := 'working'
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const errorFunction = createHogFunction({
                type: 'transformation',
                name: errorFilterTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(errorFilterTemplate.hog),
                filters: {
                    bytecode: await compileHog(`
                        // Invalid filter that will throw an error
                        throw new Error('Test error in filter')
                    `),
                },
            })

            const workingFunction = createHogFunction({
                type: 'transformation',
                name: workingTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(workingTemplate.hog),
            })

            await insertHogFunction(hub.db.postgres, teamId, errorFunction)
            await insertHogFunction(hub.db.postgres, teamId, workingFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [
                errorFunction.id,
                workingFunction.id,
            ])

            const event = createPluginEvent({ event: 'test-event' }, teamId)
            const result = await hogTransformer.transformEventAndProduceMessages(event)

            // Verify both transformations were applied
            expect(result.event?.properties?.error_filter_property).toBe('should_be_set')
            expect(result.event?.properties?.working_property).toBe('working')
            expect(result.event?.properties?.$transformations_succeeded).toContain(
                `${errorFunction.name} (${errorFunction.id})`
            )
            expect(result.event?.properties?.$transformations_succeeded).toContain(
                `${workingFunction.name} (${workingFunction.id})`
            )
        })

        it('should not check filters when FILTER_TRANSFORMATIONS_ENABLED is false', async () => {
            // Disable filter transformations
            hub.FILTER_TRANSFORMATIONS_ENABLED_TEAMS = [1, 2]

            const filterTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-test',
                name: 'Filter Template',
                description: 'A template with filters that should be ignored',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.always_apply := 'applied'
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const hogFunction = createHogFunction({
                type: 'transformation',
                name: filterTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(filterTemplate.hog),
                filters: {
                    bytecode: await compileHog(`
                    return event = 'match-me'
                    `),
                },
            })

            await insertHogFunction(hub.db.postgres, teamId, hogFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [hogFunction.id])

            const event = createPluginEvent({ event: 'match-me' }, teamId)
            const result = await hogTransformer.transformEventAndProduceMessages(event)

            expect(result.event?.properties?.always_apply).toBe('applied')
            expect(result.event?.properties?.$transformations_succeeded).toContain(
                `${hogFunction.name} (${hogFunction.id})`
            )
        })

        it('should skip transformation when none of multiple filters match', async () => {
            const multiFilterTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-test',
                name: 'Multi Filter Template',
                description: 'A template with multiple filters that should all not match',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.should_not_be_set := true
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const hogFunction = createHogFunction({
                type: 'transformation',
                name: multiFilterTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(multiFilterTemplate.hog),
                filters: {
                    bytecode: await compileHog(`
                        // First filter checks for 'match-me-1'
                        let filter1 := event = 'match-me-1'
                        // Second filter checks for 'match-me-2'
                        let filter2 := event = 'match-me-2'
                        // Only transform if at least one filter matches
                        return filter1 or filter2
                    `),
                },
            })

            await insertHogFunction(hub.db.postgres, teamId, hogFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [hogFunction.id])

            const event = createPluginEvent({ event: 'does-not-match-any' }, teamId)
            const result = await hogTransformer.transformEventAndProduceMessages(event)

            // Verify transformation was skipped since no filters matched
            expect(result.event?.properties?.should_not_be_set).toBeUndefined()
            expect(result.event?.properties?.$transformations_succeeded).toBeUndefined()
            expect(result.event?.properties?.$transformations_failed).toBeUndefined()
            expect(result.event?.properties?.$transformations_skipped).toEqual([
                `${hogFunction.name} (${hogFunction.id})`,
            ])
        })

        it('should apply transformation when at least one of multiple filters match', async () => {
            const multiFilterTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-test',
                name: 'Multi Filter Template',
                description: 'A template with multiple filters where one should match',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.should_be_set := true
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const hogFunction = createHogFunction({
                type: 'transformation',
                name: multiFilterTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(multiFilterTemplate.hog),
                filters: {
                    bytecode: await compileHog(`
                        // First filter checks for 'match-me-1'
                        let filter1 := event = 'match-me-1'
                        // Second filter checks for 'match-me-2'
                        let filter2 := event = 'match-me-2'
                        // Only transform if at least one filter matches
                        return filter1 or filter2
                    `),
                },
            })

            await insertHogFunction(hub.db.postgres, teamId, hogFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [hogFunction.id])

            const event = createPluginEvent({ event: 'match-me-1' }, teamId)
            const result = await hogTransformer.transformEventAndProduceMessages(event)

            // Verify transformation was applied since one filter matched
            expect(result.event?.properties?.should_be_set).toBe(true)
            expect(result.event?.properties?.$transformations_succeeded).toContain(
                `${hogFunction.name} (${hogFunction.id})`
            )
        })
    })

    // Add the new test suite for HogWatcher integration
    describe('transformEvent HogWatcher integration', () => {
        beforeEach(() => {
            hub.CDP_HOG_WATCHER_SAMPLE_RATE = 1
            hub.FILTER_TRANSFORMATIONS_ENABLED_TEAMS = [teamId]
        })

        it('should skip HogWatcher operations when sample rate is 0', async () => {
            // Set sample rate to 0
            hub.CDP_HOG_WATCHER_SAMPLE_RATE = 0

            // Create spies for HogWatcher methods
            const getStatesSpy = jest.spyOn(hogTransformer['hogWatcher'], 'getStates')
            const observeResultsSpy = jest.spyOn(hogTransformer['hogWatcher'], 'observeResults')

            // Create a simple transformation
            const template = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-test',
                name: 'Test Template',
                description: 'A simple test template',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.test_property := true
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const hogFunction = createHogFunction({
                type: 'transformation',
                name: template.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(template.hog),
                id: '11111111-1111-4111-a111-111111111111',
            })

            await insertHogFunction(hub.db.postgres, teamId, hogFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [hogFunction.id])

            const event = createPluginEvent({ event: 'test-event' }, teamId)
            const result = await hogTransformer.transformEventAndProduceMessages(event)

            // Verify the transformation still worked
            expect(result.event?.properties?.test_property).toBe(true)
            expect(result.event?.properties?.$transformations_succeeded).toContain(
                `${hogFunction.name} (${hogFunction.id})`
            )

            // Verify HogWatcher methods were not called
            expect(getStatesSpy).not.toHaveBeenCalled()
            expect(observeResultsSpy).not.toHaveBeenCalled()

            getStatesSpy.mockRestore()
            observeResultsSpy.mockRestore()
        })

        it('should log but not skip functions that would be disabled', async () => {
            const logSpy = jest.spyOn(logger, 'info')

            // Mock the getStates method to return a disabled state for our function
            const getStatesSpy = jest.spyOn(hogTransformer['hogWatcher'], 'getStates').mockImplementation((ids) => {
                const states: Record<string, any> = {}
                ids.forEach((id) => {
                    states[id] = {
                        state: HogWatcherState.disabledForPeriod,
                        tokens: 0,
                        rating: 0,
                    }
                })
                return Promise.resolve(states)
            })

            // Create a transformation that would normally be disabled but runs in monitoring mode
            const template = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-test',
                name: 'Would Be Disabled Template',
                description: 'A template that would be disabled but runs in monitoring mode',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.should_still_be_set := true
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const hogFunction = createHogFunction({
                type: 'transformation',
                name: template.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(template.hog),
                id: '11111111-1111-4111-a111-111111111111',
            })

            await insertHogFunction(hub.db.postgres, teamId, hogFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [hogFunction.id])

            const event = createPluginEvent({ event: 'test-event' }, teamId)
            const result = await hogTransformer.transformEventAndProduceMessages(event)

            // Verify the function still ran despite being "disabled" in monitoring mode
            expect(result.event?.properties?.should_still_be_set).toBe(true)

            // Verify transformations_succeeded contains our function (not skipped)
            expect(result.event?.properties?.$transformations_succeeded).toContain(
                `${hogFunction.name} (${hogFunction.id})`
            )

            // Verify transformations_skipped doesn't exist or is empty
            expect(result.event?.properties?.$transformations_skipped).toBeUndefined()

            // Verify that the appropriate monitoring log was created
            expect(logSpy).toHaveBeenCalledWith(
                '🧪',
                '[MONITORING MODE] Transformation would be disabled but is allowed to run for testing',
                expect.objectContaining({
                    function_id: hogFunction.id,
                    function_name: hogFunction.name,
                    team_id: teamId,
                    state: HogWatcherState.disabledForPeriod,
                })
            )

            getStatesSpy.mockRestore()
            logSpy.mockRestore()
        })

        it('should observe results for rate limiting', async () => {
            const observeResultsSpy = jest
                .spyOn(hogTransformer['hogWatcher'], 'observeResults')
                .mockImplementation(() => Promise.resolve())

            // Mock the getStates method to return healthy states
            jest.spyOn(hogTransformer['hogWatcher'], 'getStates').mockImplementation((ids) => {
                const states: Record<string, any> = {}
                ids.forEach((id) => {
                    states[id] = {
                        state: HogWatcherState.healthy,
                        tokens: 100,
                        rating: 1.0,
                    }
                })
                return Promise.resolve(states)
            })

            // Create a transformation that will be executed
            const template = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-test',
                name: 'Working Template',
                description: 'A template that should work',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.working := true
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const hogFunction = createHogFunction({
                type: 'transformation',
                name: template.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(template.hog),
            })

            await insertHogFunction(hub.db.postgres, teamId, hogFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [hogFunction.id])

            const event = createPluginEvent({ event: 'test-event' }, teamId)
            await hogTransformer.transformEventAndProduceMessages(event)

            // Verify observeResults was called with the execution results
            expect(observeResultsSpy).toHaveBeenCalled()

            // Results should be non-empty array of HogFunctionInvocationResult
            const results = observeResultsSpy.mock.calls[0][0]
            expect(results.length).toBeGreaterThan(0)
            expect(results[0]).toHaveProperty('invocation')
            expect(results[0].invocation.hogFunction.id).toBe(hogFunction.id)

            observeResultsSpy.mockRestore()
        })

        it('should log monitoring status for functions with different states', async () => {
            const logSpy = jest.spyOn(logger, 'info')

            // Two functions: one would be disabled, one healthy
            const wouldBeDisabledFunctionId = '22222222-2222-4222-a222-222222222222'
            const healthyFunctionId = '33333333-3333-4333-a333-333333333333'

            // Mock getStates to return different states for different functions
            jest.spyOn(hogTransformer['hogWatcher'], 'getStates').mockImplementation((ids) => {
                const states: Record<string, any> = {}
                ids.forEach((id) => {
                    if (id === wouldBeDisabledFunctionId) {
                        states[id] = {
                            state: HogWatcherState.disabledIndefinitely,
                            tokens: 0,
                            rating: 0,
                        }
                    } else {
                        states[id] = {
                            state: HogWatcherState.healthy,
                            tokens: 100,
                            rating: 1.0,
                        }
                    }
                })
                return Promise.resolve(states)
            })

            // Create two templates and functions
            const wouldBeDisabledTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-would-be-disabled',
                name: 'Would Be Disabled Template',
                description: 'A template that would be disabled but runs in monitoring mode',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.first_transformation := true
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const healthyTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-healthy',
                name: 'Healthy Template',
                description: 'A healthy template that should run normally',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.second_transformation := true
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const wouldBeDisabledFunction = createHogFunction({
                type: 'transformation',
                name: wouldBeDisabledTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(wouldBeDisabledTemplate.hog),
                id: wouldBeDisabledFunctionId,
                execution_order: 1,
            })

            const healthyFunction = createHogFunction({
                type: 'transformation',
                name: healthyTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(healthyTemplate.hog),
                id: healthyFunctionId,
                execution_order: 2,
            })

            await insertHogFunction(hub.db.postgres, teamId, wouldBeDisabledFunction)
            await insertHogFunction(hub.db.postgres, teamId, healthyFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [
                wouldBeDisabledFunction.id,
                healthyFunction.id,
            ])

            const event = createPluginEvent({ event: 'test-event' }, teamId)
            const result = await hogTransformer.transformEventAndProduceMessages(event)

            // Verify both functions ran despite one being "disabled" in monitoring mode
            expect(result.event?.properties?.first_transformation).toBe(true)
            expect(result.event?.properties?.second_transformation).toBe(true)

            // Verify transformations_succeeded contains both functions
            expect(result.event?.properties?.$transformations_succeeded).toContain(
                `${wouldBeDisabledFunction.name} (${wouldBeDisabledFunction.id})`
            )
            expect(result.event?.properties?.$transformations_succeeded).toContain(
                `${healthyFunction.name} (${healthyFunction.id})`
            )

            // Verify no transformations were skipped
            expect(result.event?.properties?.$transformations_skipped).toBeUndefined()

            // Verify that the appropriate monitoring log message was created for the would-be-disabled function
            expect(logSpy).toHaveBeenCalledWith(
                '🧪',
                '[MONITORING MODE] Transformation would be disabled but is allowed to run for testing',
                expect.objectContaining({
                    function_id: wouldBeDisabledFunction.id,
                    function_name: wouldBeDisabledFunction.name,
                    team_id: teamId,
                    state: HogWatcherState.disabledIndefinitely,
                    state_name: 'disabled_permanently',
                })
            )

            // Instead of checking total call count, verify the monitoring log was not created for the healthy function
            const monitoringLogCalls = logSpy.mock.calls.filter(
                (call) =>
                    call[0] === '🧪' &&
                    call[1] ===
                        '[MONITORING MODE] Transformation would be disabled but is allowed to run for testing' &&
                    call[2].function_id === healthyFunction.id
            )
            expect(monitoringLogCalls.length).toBe(0)

            logSpy.mockRestore()
        })
    })
})
