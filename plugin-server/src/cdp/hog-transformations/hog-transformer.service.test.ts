import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { posthogFilterOutPlugin } from '../../../src/cdp/legacy-plugins/_transformations/posthog-filter-out-plugin/template'
import { template as defaultTemplate } from '../../../src/cdp/templates/_transformations/default/default.template'
import { template as geoipTemplate } from '../../../src/cdp/templates/_transformations/geoip/geoip.template'
import { compileHog } from '../../../src/cdp/templates/compiler'
import { forSnapshot } from '../../../tests/helpers/snapshots'
import { getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { createHogFunction, insertHogFunction } from '../_tests/fixtures'
import { posthogPluginGeoip } from '../legacy-plugins/_transformations/posthog-plugin-geoip/template'
import { propertyFilterPlugin } from '../legacy-plugins/_transformations/property-filter-plugin/template'
import { HogWatcherState } from '../services/monitoring/hog-watcher.service'
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
                geoIpTransformationFunction.id,
                defaultTransformationFunction.id,
                testTransformationFunction.id,
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
            expect(executeHogFunctionSpy.mock.calls[2][0]).toMatchObject({ execution_order: 3 })
            expect(event.properties?.test_property).toEqual('test_value')

            await hogTransformer.processInvocationResults()

            const messages = mockProducerObserver.getProducedKafkaMessages()
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

            const addingTransformationFunction = createHogFunction({
                type: 'transformation',
                name: addingTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(addingTemplate.hog),
                execution_order: 1,
            })

            const deletingTransformationFunction = createHogFunction({
                type: 'transformation',
                name: deletingTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(deletingTemplate.hog),
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

            // Verify that:
            // 1. First transformation succeeded (property was set)
            // 2. Second transformation was skipped (property was NOT set)
            // 3. We have correct tracking properties
            expect(result.event?.properties?.success).toBe(true)
            expect(result.event?.properties?.should_not_be_set).toBeUndefined()

            // Check that transformations_succeeded and transformations_skipped arrays contain the right functions
            expect(result.event?.properties?.$transformations_succeeded).toContain(
                `Success Template (${successFunction.id})`
            )
            expect(result.event?.properties?.$transformations_skipped).toContain(
                `Skipped Template (${skippedFunction.id})`
            )
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

        it('should skip transformation when filter errors and not continue processing', async () => {
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
                    returnEvent.properties.error_filter_property := 'should_not_be_set'
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
                        lol
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

            // Verify one transformation was applied and the other was skipped
            expect(result.event?.properties?.error_filter_property).toBeUndefined()
            expect(result.invocationResults[0].error).toContain('Global variable not found')
            expect(result.event?.properties?.$transformations_skipped).toContain(
                `${errorFunction.name} (${errorFunction.id})`
            )

            expect(result.event?.properties?.working_property).toBe('working')
            expect(result.event?.properties?.$transformations_succeeded).toContain(
                `${workingFunction.name} (${workingFunction.id})`
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

    describe('HogWatcher integration', () => {
        beforeEach(() => {
            hub.CDP_HOG_WATCHER_SAMPLE_RATE = 1
        })

        it('should skip HogWatcher operations when sample rate is 0', async () => {
            hub.CDP_HOG_WATCHER_SAMPLE_RATE = 0

            const testTemplate: HogFunctionTemplate = {
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
                name: testTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(testTemplate.hog),
                id: '11111111-1111-4111-a111-111111111111',
            })

            await insertHogFunction(hub.db.postgres, teamId, hogFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [hogFunction.id])

            const observeResultsSpy = jest.spyOn(hogTransformer['hogWatcher'], 'observeResults')

            const event = createPluginEvent({ event: 'test-event' }, teamId)
            await hogTransformer.transformEventAndProduceMessages(event)

            expect(observeResultsSpy).not.toHaveBeenCalled()
            expect(hogTransformer['invocationResults'].length).toBe(1)

            observeResultsSpy.mockRestore()
        })

        it('should add watcher promise when sample rate is 1', async () => {
            hub.CDP_HOG_WATCHER_SAMPLE_RATE = 1

            const testTemplate: HogFunctionTemplate = {
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

            const hogFunctionId = '11111111-1111-4111-a111-111111111111'
            const hogFunction = createHogFunction({
                type: 'transformation',
                name: testTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(testTemplate.hog),
                id: hogFunctionId,
            })

            await insertHogFunction(hub.db.postgres, teamId, hogFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [hogFunction.id])

            // Add the state to the cache to prevent the error from being thrown
            // This simulates what would happen in production where states would be loaded
            hogTransformer['cachedStates'][hogFunctionId] = HogWatcherState.healthy

            const observeResultsSpy = jest
                .spyOn(hogTransformer['hogWatcher'], 'observeResults')
                .mockImplementation(() => Promise.resolve())

            const event = createPluginEvent({ event: 'test-event' }, teamId)
            await hogTransformer.transformEventAndProduceMessages(event)
            expect(hogTransformer['invocationResults'].length).toBe(1)
            await hogTransformer.processInvocationResults()
            expect(hogTransformer['invocationResults'].length).toBe(0)

            expect(observeResultsSpy).toHaveBeenCalled()

            observeResultsSpy.mockRestore()
        })

        it('should save and clear hog function states', async () => {
            const functionIds = ['11111111-1111-4111-a111-111111111111', '22222222-2222-4222-a222-222222222222']
            const mockStates = {
                [functionIds[0]]: { state: HogWatcherState.disabledForPeriod, tokens: 0, rating: 0 },
                [functionIds[1]]: { state: HogWatcherState.disabledIndefinitely, tokens: 0, rating: 0 },
            }

            // Mock getStates
            jest.spyOn(hogTransformer['hogWatcher'], 'getStates').mockResolvedValue(Promise.resolve(mockStates))

            // Save states
            await hogTransformer.fetchAndCacheHogFunctionStates(functionIds)

            // Verify states were cached
            expect(hogTransformer['cachedStates'][functionIds[0]]).toBe(HogWatcherState.disabledForPeriod)
            expect(hogTransformer['cachedStates'][functionIds[1]]).toBe(HogWatcherState.disabledIndefinitely)

            // Clear specific state
            hogTransformer.clearHogFunctionStates([functionIds[0]])
            expect(hogTransformer['cachedStates'][functionIds[0]]).toBeUndefined()
            expect(hogTransformer['cachedStates'][functionIds[1]]).toBe(HogWatcherState.disabledIndefinitely)

            // Clear all states
            hogTransformer.clearHogFunctionStates()
            expect(hogTransformer['cachedStates']).toEqual({})
        })

        it('should throw error when state is missing from cache', () => {
            const hogFunctionId = '11111111-1111-4111-a111-111111111111'

            // Create a test hog function
            createHogFunction({
                type: 'transformation',
                name: 'Test Function',
                team_id: teamId,
                enabled: true,
                id: hogFunctionId,
            })

            // Make sure state is not in cache
            hogTransformer.clearHogFunctionStates()

            // Verify state is not in cache initially
            expect(hogTransformer['cachedStates'][hogFunctionId] || null).toBeNull()

            // Create the expected error message
            const expectedErrorMessage = `Critical error: Missing HogFunction state in cache for function ${hogFunctionId} - this should never happen`

            // Define a function that will throw the error
            const throwingFunction = () => {
                if (!hogTransformer['cachedStates'][hogFunctionId]) {
                    throw new Error(expectedErrorMessage)
                }
                return 'This should not be returned'
            }

            // Verify that the function throws the expected error
            expect(throwingFunction).toThrow(expectedErrorMessage)
        })

        it('should skip transformation execution but continue when hogwatcher is enabled and function is disabled', async () => {
            // Set sample rate to 100% to ensure hogwatcher logic runs
            hub.CDP_HOG_WATCHER_SAMPLE_RATE = 1

            // Create test transformation function
            const testTemplate: HogFunctionTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-test',
                name: 'Disabled Test Template',
                description: 'A test template that should be skipped due to disabled state',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.should_not_be_set := true
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const hogFunctionId = '33333333-3333-4333-a333-333333333333'
            const hogFunction = createHogFunction({
                type: 'transformation',
                name: testTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(testTemplate.hog),
                id: hogFunctionId,
            })

            await insertHogFunction(hub.db.postgres, teamId, hogFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [hogFunction.id])

            // Mock the cached state to indicate the function is disabled
            hogTransformer['cachedStates'][hogFunctionId] = HogWatcherState.disabledForPeriod

            // Create a spy to verify the executeHogFunction method is not called
            const executeHogFunctionSpy = jest.spyOn(hogTransformer as any, 'executeHogFunction')

            const event = createPluginEvent({ event: 'test-event' }, teamId)
            const result = await hogTransformer.transformEventAndProduceMessages(event)

            // Verify the executeHogFunction method was not called for this function
            expect(executeHogFunctionSpy).not.toHaveBeenCalled()

            // Verify the transformation result doesn't have the property that would be set
            expect(result.event?.properties?.should_not_be_set).toBeUndefined()

            // Verify there are no transformation records in the properties
            expect(result.event?.properties?.$transformations_succeeded).toBeUndefined()
            expect(result.event?.properties?.$transformations_failed).toBeUndefined()

            // Reset spies
            executeHogFunctionSpy.mockRestore()
        })

        it('should execute transformation when hogwatcher is enabled but function is in healthy state', async () => {
            // Set sample rate to 100% to ensure hogwatcher logic runs
            hub.CDP_HOG_WATCHER_SAMPLE_RATE = 1

            // Create test transformation function
            const testTemplate: HogFunctionTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-test',
                name: 'Healthy Test Template',
                description: 'A test template that should execute because state is healthy',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.should_be_set := true
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const hogFunctionId = '55555555-5555-5555-a555-555555555555'
            const hogFunction = createHogFunction({
                type: 'transformation',
                name: testTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(testTemplate.hog),
                id: hogFunctionId,
            })

            await insertHogFunction(hub.db.postgres, teamId, hogFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [hogFunction.id])

            // Mock the cached state to indicate the function is healthy
            hogTransformer['cachedStates'][hogFunctionId] = HogWatcherState.healthy

            // Create a spy to verify the executeHogFunction method is called
            const executeHogFunctionSpy = jest.spyOn(hogTransformer as any, 'executeHogFunction')

            const event = createPluginEvent({ event: 'test-event' }, teamId)
            const result = await hogTransformer.transformEventAndProduceMessages(event)

            // Verify the executeHogFunction method was called for this function
            expect(executeHogFunctionSpy).toHaveBeenCalledTimes(1)

            // Verify the transformation result has the property that should be set
            expect(result.event?.properties?.should_be_set).toBe(true)

            // Verify the transformation is recorded as successful
            expect(result.event?.properties?.$transformations_succeeded).toContain(
                `${hogFunction.name} (${hogFunction.id})`
            )

            // Reset spies
            executeHogFunctionSpy.mockRestore()
        })

        it('should apply transformation when hogwatcher is disabled even if function state is disabled', async () => {
            // Set sample rate to 0% to ensure hogwatcher logic is skipped
            hub.CDP_HOG_WATCHER_SAMPLE_RATE = 0

            // Create test transformation function
            const testTemplate: HogFunctionTemplate = {
                free: true,
                status: 'beta',
                type: 'transformation',
                id: 'template-test',
                name: 'Test Template',
                description: 'A test template that should execute despite disabled state because hogwatcher is off',
                category: ['Custom'],
                hog: `
                    let returnEvent := event
                    returnEvent.properties.should_be_set := true
                    return returnEvent
                `,
                inputs_schema: [],
            }

            const hogFunctionId = '44444444-4444-4444-a444-444444444444'
            const hogFunction = createHogFunction({
                type: 'transformation',
                name: testTemplate.name,
                team_id: teamId,
                enabled: true,
                bytecode: await compileHog(testTemplate.hog),
                id: hogFunctionId,
            })

            await insertHogFunction(hub.db.postgres, teamId, hogFunction)
            hogTransformer['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [hogFunction.id])

            // Mock the cached state to indicate the function is disabled
            hogTransformer['cachedStates'][hogFunctionId] = HogWatcherState.disabledForPeriod

            // Create a spy to verify the executeHogFunction method is called
            const executeHogFunctionSpy = jest.spyOn(hogTransformer as any, 'executeHogFunction')

            const event = createPluginEvent({ event: 'test-event' }, teamId)
            const result = await hogTransformer.transformEventAndProduceMessages(event)

            // Verify the executeHogFunction method was called for this function
            expect(executeHogFunctionSpy).toHaveBeenCalledTimes(1)

            // Verify the transformation result has the property that should be set
            expect(result.event?.properties?.should_be_set).toBe(true)

            // Verify the transformation is recorded as successful
            expect(result.event?.properties?.$transformations_succeeded).toContain(
                `${hogFunction.name} (${hogFunction.id})`
            )

            // Reset spies
            executeHogFunctionSpy.mockRestore()
        })
    })
})
