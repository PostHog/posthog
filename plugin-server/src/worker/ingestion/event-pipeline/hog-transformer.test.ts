import { HogTransformer } from './hog-transformer'
import { PluginEvent } from '@posthog/plugin-scaffold'
import { status } from '../../../utils/status'
import { Hub } from '../../../types'
import { HogFunctionManager } from '../../../cdp/hog-function-manager'
import { HogExecutor } from '../../../cdp/hog-executor'
import { createHub } from 'utils/db/hub'
import { createHogFunction } from '../../../cdp/'

jest.mock('../../../utils/status', () => ({
    status: {
        warn: jest.fn(),
        info: jest.fn(),
        debug: jest.fn(),
    },
}))

describe('HogTransformer', () => {
    let hub: Hub
    let hogTransformer: HogTransformer
    let hogFunctionManager: HogFunctionManager
    let hogExecutor: HogExecutor

    beforeEach(async () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2024-06-07T12:00:00.000Z'))
    
        hub = await createHub()
        hogFunctionManager = new HogFunctionManager(hub) // needed for spying 
        hogTransformer = new HogTransformer(hub)
    })

    describe('transformEvent', async () => {
        it('handles geoip lookup transformation', async () => {
            const geoIpFunction = createHogFunction({
                id: 'test-function',
                team_id: 1,
                code: `
                    function transform(event, { geoipLookup }) {
                        const geoData = geoipLookup(event.ip)
                        return {
                            properties: {
                                geoip_data: geoData
                            }
                        }
                    }
                `
            })

            jest.spyOn(hogFunctionManager, 'getTeamHogFunctions').mockResolvedValue([geoIpFunction])

            const event: PluginEvent = {
                event: 'test',
                team_id: 1,
                properties: { original: true },
                distinct_id: 'user123',
                timestamp: '2024-06-07T12:00:00.000Z',
                uuid: 'test-uuid',
                ip: '127.0.0.1',
                site_url: 'http://localhost',
                now: '2024-06-07T12:00:00.000Z'
            }

            const result = await hogTransformer.transformEvent(event)
            
            expect(result.properties).toEqual({
                original: true,
                geoip_data: {
                    country: { names: { en: 'United States' } },
                    city: { names: { en: 'San Francisco' } }
                }
            })
            expect(hub.mmdb!.city).toHaveBeenCalledWith('127.0.0.1')
        })

        it('handles multiple transformations in sequence', async () => {
            const transform1 = createHogFunction({
                id: 'transform-1',
                team_id: 1,
                code: `
                    function transform(event) {
                        return {
                            properties: {
                                transform1: true
                            }
                        }
                    }
                `
            })

            const transform2 = createHogFunction({
                id: 'transform-2',
                team_id: 1,
                code: `
                    function transform(event) {
                        return {
                            properties: {
                                transform2: true,
                                saw_transform1: !!event.properties.transform1
                            }
                        }
                    }
                `
            })

            jest.spyOn(hogFunctionManager, 'getTeamHogFunctions').mockResolvedValue([transform1, transform2])

            const event: PluginEvent = {
                event: 'test',
                team_id: 1,
                properties: { original: true },
                distinct_id: 'user123',
                timestamp: '2024-06-07T12:00:00.000Z',
                uuid: 'test-uuid'
            }

            const result = await hogTransformer.transformEvent(event)

            expect(result.properties).toEqual({
                original: true,
                transform1: true,
                transform2: true,
                saw_transform1: true
            })
        })

        it('handles transformation errors', async () => {
            const badTransform = createHogFunction({
                id: 'bad-transform',
                team_id: 1,
                code: `
                    function transform(event) {
                        throw new Error('Transformation failed!')
                    }
                `
            })

            jest.spyOn(hogFunctionManager, 'getTeamHogFunctions').mockResolvedValue([badTransform])

            const event: PluginEvent = {
                event: 'test',
                team_id: 1,
                properties: { original: true },
                distinct_id: 'user123',
                timestamp: '2024-06-07T12:00:00.000Z',
                uuid: 'test-uuid'
            }

            const result = await hogTransformer.transformEvent(event)

            expect(result).toEqual(event)
            expect(status.warn).toHaveBeenCalledWith(
                '⚠️',
                'Error in transformation',
                expect.objectContaining({
                    function_id: 'bad-transform',
                    team_id: 1
                })
            )
        })

        it('validates property types', async () => {
            const invalidPropsTransform = createHogFunction({
                id: 'invalid-props',
                team_id: 1,
                code: `
                    function transform(event) {
                        return {
                            properties: {
                                func: () => {}, // Functions are not valid property values
                                valid: 'string'
                            }
                        }
                    }
                `
            })

            jest.spyOn(hogFunctionManager, 'getTeamHogFunctions').mockResolvedValue([invalidPropsTransform])

            const event: PluginEvent = {
                event: 'test',
                team_id: 1,
                properties: { original: true },
                distinct_id: 'user123',
                timestamp: '2024-06-07T12:00:00.000Z',
                uuid: 'test-uuid'
            }

            const result = await hogTransformer.transformEvent(event)

            expect(result).toEqual(event)
            expect(status.warn).toHaveBeenCalledWith(
                '⚠️',
                'Invalid transformation result - invalid properties',
                expect.objectContaining({
                    function_id: 'invalid-props'
                })
            )
        })
    })
}) 