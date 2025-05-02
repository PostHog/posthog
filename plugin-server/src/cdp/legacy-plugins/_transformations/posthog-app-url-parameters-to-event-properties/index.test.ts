import { PluginEvent } from '@posthog/plugin-scaffold'

import { LocalMeta, PluginConfig, processEvent, setupPlugin } from './index'

/**
 * Given a url, construct a page view event.
 *
 * @param $current_url The current url of the page view
 * @returns A new PostHog page view event
 */
function buildPageViewEvent($current_url: string): PluginEvent {
    const event: PluginEvent = {
        properties: { $current_url },
        distinct_id: 'distinct_id',
        ip: '1.2.3.4',
        site_url: 'posthog.com',
        team_id: 0,
        now: '2022-06-17T20:21:31.778000+00:00',
        event: '$pageview',
        uuid: '01817354-06bb-0000-d31c-2c4eed374100',
    }

    return event
}

const defaultConfig: PluginConfig = {
    parameters: 'myUrlParameter',
    prefix: '',
    suffix: '',
    setAsUserProperties: 'false',
    setAsInitialUserProperties: 'false',
    ignoreCase: 'false',
    alwaysJson: 'false',
}

const pluginJSON = require('./plugin.json')

function buildMockMeta(partialConfig: Partial<PluginConfig> = {}): LocalMeta {
    const config: PluginConfig = { ...defaultConfig, ...partialConfig }
    return {
        global: {
            ignoreCase: config.ignoreCase === 'true',
            setAsInitialUserProperties: config.setAsInitialUserProperties === 'true',
            setAsUserProperties: config.setAsUserProperties === 'true',
            alwaysJson: config.alwaysJson === 'true',
            parameters: new Set(
                config.parameters ? config.parameters.split(',').map((parameter) => parameter.trim()) : null
            ),
        },
        config: config,
    } as LocalMeta
}

describe('ParamsToPropertiesPlugin', () => {
    let mockMeta: LocalMeta

    beforeEach(() => {
        jest.clearAllMocks()

        mockMeta = buildMockMeta()
    })

    describe('setupPlugin', () => {
        it('should set one item to whitelist', () => {
            const meta = {
                global: {
                    parameters: new Set(),
                },
                config: {
                    parameters: 'one_item',
                    prefix: '',
                    suffix: '',
                    setAsUserProperties: 'false',
                    setAsInitialUserProperties: 'false',
                    ignoreCase: 'false',
                    alwaysJson: 'false',
                },
            } as LocalMeta

            expect(meta.global.parameters.size).toBe(0)

            setupPlugin(meta)

            expect(meta.global.parameters.size).toBe(1)
        })

        it('should set three item to whitelist', () => {
            const meta = {
                global: {
                    parameters: new Set(),
                },
                config: {
                    parameters: 'one_item, two_item,three_item',
                    prefix: '',
                    suffix: '',
                    setAsUserProperties: 'false',
                    setAsInitialUserProperties: 'false',
                    ignoreCase: 'false',
                    alwaysJson: 'false',
                },
            } as LocalMeta

            expect(meta.global.parameters.size).toBe(0)

            setupPlugin(meta)

            expect(meta.global.parameters.size).toBe(3)
            expect(meta.global.parameters.has('one_item')).toBeTruthy()
            expect(meta.global.parameters.has('two_item')).toBeTruthy()
            expect(meta.global.parameters.has('three_item')).toBeTruthy()
        })

        it('should clear global whitelist when config is missing whitelist', () => {
            const meta = {
                global: {
                    parameters: new Set(['one_item']),
                },
                config: {
                    prefix: '',
                    suffix: '',
                    setAsUserProperties: 'false',
                    setAsInitialUserProperties: 'false',
                    ignoreCase: 'false',
                    alwaysJson: 'false',
                },
            } as LocalMeta

            expect(meta.global.parameters.size).toBe(1)

            setupPlugin(meta)

            expect(meta.global.parameters.size).toBe(0)
        })
    })

    describe('plugin.json', () => {
        it('should contain all properties of PluginConfig', () => {
            expect(pluginJSON.config).toBeTruthy()
            if (pluginJSON.config) {
                const fields = new Set<string>()
                for (const item of pluginJSON.config) {
                    fields.add(item.key)
                }

                expect(fields.has('ignoreCase')).toBeTruthy()
                expect(fields.has('prefix')).toBeTruthy()
                expect(fields.has('setAsInitialUserProperties')).toBeTruthy()
                expect(fields.has('setAsUserProperties')).toBeTruthy()
                expect(fields.has('suffix')).toBeTruthy()
                expect(fields.has('parameters')).toBeTruthy()
                expect(fields.has('alwaysJson')).toBeTruthy()
                expect(fields.size).toEqual(7)
            }
        })

        it('should match types of all properties of PluginConfig', () => {
            expect(pluginJSON.config).toBeTruthy()
            if (pluginJSON.config) {
                const fields = new Map<string, string>()
                for (const item of pluginJSON.config) {
                    fields.set(item.key, item.type)
                }

                expect(fields.get('ignoreCase')).toEqual('choice')
                expect(fields.get('prefix')).toEqual('string')
                expect(fields.get('setAsInitialUserProperties')).toEqual('choice')
                expect(fields.get('setAsUserProperties')).toEqual('choice')
                expect(fields.get('suffix')).toEqual('string')
                expect(fields.get('parameters')).toEqual('string')
                expect(fields.get('alwaysJson')).toEqual('choice')
            }
        })
    })

    describe('processEvent', () => {
        it("shouldn't change properties count", () => {
            const sourceEvent = buildPageViewEvent('https://posthog.com/test?plugin=1')
            if (sourceEvent.properties) {
                const sourcePropertiesCount = Object.keys(sourceEvent?.properties).length
                const processedEvent = processEvent(sourceEvent, mockMeta)

                if (processedEvent.properties) {
                    expect(Object.keys(processedEvent.properties).length).toEqual(sourcePropertiesCount)
                } else {
                    expect(processedEvent.properties).toBeTruthy()
                }
            } else {
                expect(sourceEvent.properties).toBeTruthy()
            }
        })

        it('should add 1 property', () => {
            const sourceEvent = buildPageViewEvent('https://posthog.com/test?plugin=1&myUrlParameter=1')

            if (sourceEvent.properties) {
                expect(sourceEvent.properties['myUrlParameter']).not.toBeTruthy()
                expect(mockMeta.global.alwaysJson).toBeFalsy()

                const sourcePropertiesCount = Object.keys(sourceEvent?.properties).length
                const processedEvent = processEvent(sourceEvent, mockMeta)

                if (processedEvent.properties) {
                    expect(Object.keys(processedEvent.properties).length).toBeGreaterThan(sourcePropertiesCount)
                    expect(Object.keys(processedEvent.properties).length).toEqual(sourcePropertiesCount + 1)
                    expect(processedEvent.properties['myUrlParameter']).toBeTruthy()
                    expect(processedEvent.properties.myUrlParameter).toEqual('1')
                } else {
                    expect(processedEvent.properties).toBeTruthy()
                }
            } else {
                expect(sourceEvent.properties).toBeTruthy()
            }
        })

        it('should add 2 property', () => {
            const sourceEvent = buildPageViewEvent('https://posthog.com/test?plugin=1&myUrlParameter=1')

            if (sourceEvent.properties) {
                expect(sourceEvent.properties['myUrlParameter']).not.toBeTruthy()

                const sourcePropertiesCount = Object.keys(sourceEvent?.properties).length
                const processedEvent = processEvent(
                    sourceEvent,
                    buildMockMeta({ parameters: 'plugin, myUrlParameter' })
                )

                if (processedEvent.properties) {
                    expect(Object.keys(processedEvent.properties).length).toBeGreaterThan(sourcePropertiesCount)
                    expect(Object.keys(processedEvent.properties).length).toEqual(sourcePropertiesCount + 2)
                    expect(processedEvent.properties['plugin']).toBeTruthy()
                    expect(processedEvent.properties['myUrlParameter']).toBeTruthy()
                } else {
                    expect(processedEvent.properties).toBeTruthy()
                }
            } else {
                expect(sourceEvent.properties).toBeTruthy()
            }
        })

        it('should add 1 property and 1 $set property', () => {
            const sourceEvent = buildPageViewEvent('https://posthog.com/test?plugin=1&myUrlParameter=1')

            if (sourceEvent.properties) {
                expect(sourceEvent.properties['myUrlParameter']).not.toBeTruthy()
                expect(sourceEvent.properties['$set']).not.toBeTruthy()

                const sourcePropertiesCount = Object.keys(sourceEvent?.properties).length
                const processedEvent = processEvent(sourceEvent, buildMockMeta({ setAsUserProperties: 'true' }))

                if (processedEvent.properties) {
                    expect(Object.keys(processedEvent.properties).length).toBeGreaterThan(sourcePropertiesCount)
                    expect(Object.keys(processedEvent.properties).length).toEqual(sourcePropertiesCount + 2)
                    expect(processedEvent.properties['myUrlParameter']).toBeTruthy()
                    expect(processedEvent.properties['$set']).toBeTruthy()
                    expect(processedEvent.properties.$set['myUrlParameter']).toBeTruthy()
                } else {
                    expect(processedEvent.properties).toBeTruthy()
                }
            } else {
                expect(sourceEvent.properties).toBeTruthy()
            }
        })

        it('should add 1 property and 1 $set_once property', () => {
            const sourceEvent = buildPageViewEvent('https://posthog.com/test?plugin=1&myUrlParameter=1')

            if (sourceEvent.properties) {
                expect(sourceEvent.properties['myUrlParameter']).not.toBeTruthy()
                expect(sourceEvent.properties['$set_once']).not.toBeTruthy()

                const sourcePropertiesCount = Object.keys(sourceEvent?.properties).length
                const processedEvent = processEvent(sourceEvent, buildMockMeta({ setAsInitialUserProperties: 'true' }))

                if (processedEvent.properties) {
                    expect(Object.keys(processedEvent.properties).length).toBeGreaterThan(sourcePropertiesCount)
                    expect(Object.keys(processedEvent.properties).length).toEqual(sourcePropertiesCount + 2)
                    expect(processedEvent.properties['myUrlParameter']).toBeTruthy()
                    expect(processedEvent.properties['$set_once']).toBeTruthy()
                    expect(processedEvent.properties.$set_once['initial_myUrlParameter']).toBeTruthy()
                } else {
                    expect(processedEvent.properties).toBeTruthy()
                }
            } else {
                expect(sourceEvent.properties).toBeTruthy()
            }
        })

        it('should add 1 property, 1 $set property and 1 $set_once property', () => {
            const sourceEvent = buildPageViewEvent('https://posthog.com/test?plugin=1&myUrlParameter=1')

            if (sourceEvent.properties) {
                expect(sourceEvent.properties['myUrlParameter']).not.toBeTruthy()
                expect(sourceEvent.properties['$set']).not.toBeTruthy()
                expect(sourceEvent.properties['$set_once']).not.toBeTruthy()

                const sourcePropertiesCount = Object.keys(sourceEvent?.properties).length
                const processedEvent = processEvent(
                    sourceEvent,
                    buildMockMeta({ setAsUserProperties: 'true', setAsInitialUserProperties: 'true' })
                )

                if (processedEvent.properties) {
                    expect(Object.keys(processedEvent.properties).length).toBeGreaterThan(sourcePropertiesCount)
                    expect(Object.keys(processedEvent.properties).length).toEqual(sourcePropertiesCount + 3)
                    expect(processedEvent.properties['myUrlParameter']).toBeTruthy()
                    expect(processedEvent.properties['$set']).toBeTruthy()
                    expect(processedEvent.properties['$set_once']).toBeTruthy()
                    expect(processedEvent.properties.$set['myUrlParameter']).toBeTruthy()
                    expect(processedEvent.properties.$set_once['initial_myUrlParameter']).toBeTruthy()
                } else {
                    expect(processedEvent.properties).toBeTruthy()
                }
            } else {
                expect(sourceEvent.properties).toBeTruthy()
            }
        })

        it('should add 1 property with prefix', () => {
            const sourceEvent = buildPageViewEvent('https://posthog.com/test?plugin=1&myUrlParameter=1')

            if (sourceEvent.properties) {
                expect(sourceEvent.properties['prefix_myUrlParameter']).not.toBeDefined()

                const sourcePropertiesCount = Object.keys(sourceEvent?.properties).length
                const processedEvent = processEvent(sourceEvent, buildMockMeta({ prefix: 'prefix_' }))

                if (processedEvent.properties) {
                    expect(Object.keys(processedEvent.properties).length).toBeGreaterThan(sourcePropertiesCount)
                    expect(Object.keys(processedEvent.properties).length).toEqual(sourcePropertiesCount + 1)
                    expect(processedEvent.properties['prefix_myUrlParameter']).toBeDefined()
                } else {
                    expect(processedEvent.properties).toBeDefined()
                }
            } else {
                expect(sourceEvent.properties).toBeDefined()
            }
        })

        it('should add 1 property with suffix', () => {
            const sourceEvent = buildPageViewEvent('https://posthog.com/test?plugin=1&myUrlParameter=1')

            if (sourceEvent.properties) {
                expect(sourceEvent.properties['myUrlParameter_suffix']).not.toBeDefined()

                const sourcePropertiesCount = Object.keys(sourceEvent?.properties).length
                const processedEvent = processEvent(sourceEvent, buildMockMeta({ suffix: '_suffix' }))

                if (processedEvent.properties) {
                    expect(Object.keys(processedEvent.properties).length).toBeGreaterThan(sourcePropertiesCount)
                    expect(Object.keys(processedEvent.properties).length).toEqual(sourcePropertiesCount + 1)
                    expect(processedEvent.properties['myUrlParameter_suffix']).toBeDefined()
                } else {
                    expect(processedEvent.properties).toBeDefined()
                }
            } else {
                expect(sourceEvent.properties).toBeDefined()
            }
        })

        it('should add 1 property with prefix and suffix', () => {
            const sourceEvent = buildPageViewEvent('https://posthog.com/test?plugin=1&myUrlParameter=1')

            if (sourceEvent.properties) {
                expect(sourceEvent.properties['prefix_myUrlParameter_suffix']).not.toBeDefined()

                const sourcePropertiesCount = Object.keys(sourceEvent?.properties).length
                const processedEvent = processEvent(
                    sourceEvent,
                    buildMockMeta({ prefix: 'prefix_', suffix: '_suffix' })
                )

                if (processedEvent.properties) {
                    expect(Object.keys(processedEvent.properties).length).toBeGreaterThan(sourcePropertiesCount)
                    expect(Object.keys(processedEvent.properties).length).toEqual(sourcePropertiesCount + 1)
                    expect(processedEvent.properties['prefix_myUrlParameter_suffix']).toBeDefined()
                } else {
                    expect(processedEvent.properties).toBeDefined()
                }
            } else {
                expect(sourceEvent.properties).toBeDefined()
            }
        })

        it("shouldn't add properties when $current_url is undefined", () => {
            const sourceEvent = {
                ...buildPageViewEvent('https://posthog.com/test?plugin=1&myUrlParameter=1'),
                ...{ properties: { $current_url: undefined } },
            }

            if (sourceEvent.properties) {
                const sourcePropertiesCount = Object.keys(sourceEvent?.properties).length
                const processedEvent = processEvent(sourceEvent, mockMeta)

                if (processedEvent.properties) {
                    expect(Object.keys(processedEvent.properties).length).toEqual(sourcePropertiesCount)
                    expect(processedEvent.properties['myUrlParameter']).not.toBeDefined()
                } else {
                    expect(processedEvent.properties).toBeDefined()
                }
            } else {
                expect(sourceEvent.properties).toBeDefined()
            }
        })

        it("shouldn't add properties when properties is undefined", () => {
            const sourceEvent = {
                ...buildPageViewEvent('https://posthog.com/test?plugin=1&myUrlParameter=1'),
                ...{ properties: undefined },
            }

            expect(sourceEvent.properties).not.toBeDefined()

            const processedEvent = processEvent(sourceEvent, mockMeta)
            expect(processedEvent.properties).not.toBeDefined()
        })

        it('should add 1 property regardless of case', () => {
            const sourceEvent = buildPageViewEvent('https://posthog.com/test?plugin=1&MyUrlParameter=1')

            if (sourceEvent.properties) {
                expect(sourceEvent.properties['myUrlParameter']).not.toBeDefined()

                const sourcePropertiesCount = Object.keys(sourceEvent?.properties).length
                const processedEvent = processEvent(sourceEvent, buildMockMeta({ ignoreCase: 'true' }))

                if (processedEvent.properties) {
                    expect(Object.keys(processedEvent.properties).length).toBeGreaterThan(sourcePropertiesCount)
                    expect(Object.keys(processedEvent.properties).length).toEqual(sourcePropertiesCount + 1)
                    expect(processedEvent.properties['myUrlParameter']).toBeDefined()
                } else {
                    expect(processedEvent.properties).toBeDefined()
                }
            } else {
                expect(sourceEvent.properties).toBeDefined()
            }
        })

        it("shouldn't add properties respecting case missmatch", () => {
            const sourceEvent = buildPageViewEvent('https://posthog.com/test?plugin=1&MyUrlParameter=1')

            if (sourceEvent.properties) {
                expect(sourceEvent.properties['myUrlParameter']).not.toBeDefined()

                const sourcePropertiesCount = Object.keys(sourceEvent?.properties).length
                const processedEvent = processEvent(sourceEvent, buildMockMeta())

                if (processedEvent.properties) {
                    expect(Object.keys(processedEvent.properties).length).toEqual(sourcePropertiesCount)
                    expect(processedEvent.properties['myUrlParameter']).not.toBeDefined()
                } else {
                    expect(processedEvent.properties).toBeDefined()
                }
            } else {
                expect(sourceEvent.properties).toBeDefined()
            }
        })

        it('should add 1 property regardless of case with prefix and suffix', () => {
            const sourceEvent = buildPageViewEvent('https://posthog.com/test?plugin=1&MyUrlParameter=1')

            if (sourceEvent.properties) {
                expect(sourceEvent.properties['myUrlParameter']).not.toBeDefined()

                const sourcePropertiesCount = Object.keys(sourceEvent?.properties).length
                const processedEvent = processEvent(
                    sourceEvent,
                    buildMockMeta({ ignoreCase: 'true', prefix: 'prefix_', suffix: '_suffix' })
                )

                if (processedEvent.properties) {
                    expect(Object.keys(processedEvent.properties).length).toBeGreaterThan(sourcePropertiesCount)
                    expect(Object.keys(processedEvent.properties).length).toEqual(sourcePropertiesCount + 1)
                    expect(processedEvent.properties['prefix_myUrlParameter_suffix']).toBeDefined()
                } else {
                    expect(processedEvent.properties).toBeDefined()
                }
            } else {
                expect(sourceEvent.properties).toBeDefined()
            }
        })

        it('should add 1 property, 1 $set property and 1 $set_once property regardless of case with prefix and suffix', () => {
            const sourceEvent = buildPageViewEvent('https://posthog.com/test?plugin=1&MyUrlParameter=1')

            if (sourceEvent.properties) {
                expect(sourceEvent.properties['myUrlParameter']).not.toBeDefined()
                expect(sourceEvent.properties['$set']).not.toBeDefined()
                expect(sourceEvent.properties['$set_once']).not.toBeDefined()

                const sourcePropertiesCount = Object.keys(sourceEvent?.properties).length
                const processedEvent = processEvent(
                    sourceEvent,
                    buildMockMeta({
                        ignoreCase: 'true',
                        prefix: 'prefix_',
                        suffix: '_suffix',
                        setAsUserProperties: 'true',
                        setAsInitialUserProperties: 'true',
                    })
                )

                if (processedEvent.properties) {
                    expect(Object.keys(processedEvent.properties).length).toBeGreaterThan(sourcePropertiesCount)
                    expect(Object.keys(processedEvent.properties).length).toEqual(sourcePropertiesCount + 3)
                    expect(processedEvent.properties['prefix_myUrlParameter_suffix']).toBeDefined()
                    expect(processedEvent.properties['$set']).toBeDefined()
                    expect(processedEvent.properties.$set['prefix_myUrlParameter_suffix']).toBeDefined()
                    expect(processedEvent.properties['$set_once']).toBeDefined()
                    expect(processedEvent.properties.$set_once['initial_prefix_myUrlParameter_suffix']).toBeDefined()
                } else {
                    expect(processedEvent.properties).toBeDefined()
                }
            } else {
                expect(sourceEvent.properties).toBeDefined()
            }
        })
        ;[
            {
                label: '',
                ignoreCase: 'false',
                prefix: '',
                suffix: '',
                setAsUserProperties: '',
                setAsInitialUserProperties: '',
            },
            {
                label: 'ignoring case',
                ignoreCase: 'true',
                prefix: '',
                suffix: '',
                setAsUserProperties: '',
                setAsInitialUserProperties: '',
            },
            {
                label: 'with a prefix',
                ignoreCase: 'false',
                prefix: 'prefix_',
                suffix: '',
                setAsUserProperties: '',
                setAsInitialUserProperties: '',
            },
            {
                label: 'with a suffix',
                ignoreCase: 'false',
                prefix: '',
                suffix: '_suffix',
                setAsUserProperties: '',
                setAsInitialUserProperties: '',
            },
            {
                label: 'with a prefix and a suffix',
                ignoreCase: 'false',
                prefix: 'prefix_',
                suffix: '_suffix',
                setAsUserProperties: '',
                setAsInitialUserProperties: '',
            },
            {
                label: 'with a $set property',
                ignoreCase: 'false',
                prefix: '',
                suffix: '',
                setAsUserProperties: 'true',
                setAsInitialUserProperties: '',
            },
            {
                label: 'with a $set_once property',
                ignoreCase: 'false',
                prefix: '',
                suffix: '',
                setAsUserProperties: '',
                setAsInitialUserProperties: 'true',
            },
            {
                label: 'with a $set and a $set_once property',
                ignoreCase: 'false',
                prefix: '',
                suffix: '',
                setAsUserProperties: 'true',
                setAsInitialUserProperties: 'true',
            },
            {
                label: 'with a prefix, a suffix, a $set, and a $set_once property',
                ignoreCase: 'false',
                prefix: 'preefix_',
                suffix: '_suffax',
                setAsUserProperties: 'true',
                setAsInitialUserProperties: 'true',
            },
        ].forEach((testOptions) => {
            it(`should add 1 multivalue property ${testOptions['label']}`, () => {
                const testParameterBase = 'multiValueParam'
                const testMockMeta = buildMockMeta({
                    ignoreCase: testOptions['ignoreCase'] === 'true' ? 'true' : 'false',
                    prefix: testOptions['prefix'],
                    suffix: testOptions['suffix'],
                    setAsUserProperties: testOptions['setAsUserProperties'] === 'true' ? 'true' : 'false',
                    setAsInitialUserProperties: testOptions['setAsInitialUserProperties'] === 'true' ? 'true' : 'false',
                    parameters: testParameterBase,
                })
                const testData = JSON.stringify(['1', '2'])

                let testParameter = testParameterBase

                if (testOptions['prefix'].length > 0) {
                    testParameter = `${testOptions['prefix']}${testParameter}`
                }

                if (testOptions['suffix'].length > 0) {
                    testParameter = `${testParameter}${testOptions['suffix']}`
                }

                const eventParameter =
                    testOptions['ignoreCase'] === 'true' ? testParameterBase.toUpperCase() : testParameterBase
                const sourceEvent = buildPageViewEvent(
                    `https://posthog.com/test?plugin=1&${eventParameter}=1&${eventParameter}=2`
                )

                if (sourceEvent.properties) {
                    expect(sourceEvent.properties[testParameter]).not.toBeDefined()

                    const sourcePropertiesCount = Object.keys(sourceEvent?.properties).length
                    const addlPropsCount =
                        1 +
                        (testOptions['setAsUserProperties'] === 'true' ? 1 : 0) +
                        (testOptions['setAsInitialUserProperties'] === 'true' ? 1 : 0)
                    const processedEvent = processEvent(sourceEvent, testMockMeta)

                    if (processedEvent.properties) {
                        // the setAs options are additive

                        if (testOptions['setAsUserProperties'] === 'true') {
                            expect(Object.keys(processedEvent.properties.$set)).toBeDefined()
                            expect(Object.keys(processedEvent.properties.$set).length).toEqual(1)
                            expect(processedEvent.properties.$set[testParameter]).toBeDefined()
                            expect(processedEvent.properties.$set[testParameter]).toEqual(testData)
                        }

                        if (testOptions['setAsInitialUserProperties'] === 'true') {
                            expect(Object.keys(processedEvent.properties.$set_once)).toBeDefined()
                            expect(Object.keys(processedEvent.properties.$set_once).length).toEqual(1)
                            expect(processedEvent.properties.$set_once[`initial_${testParameter}`]).toBeDefined()
                            expect(processedEvent.properties.$set_once[`initial_${testParameter}`]).toEqual(testData)
                        }

                        expect(Object.keys(processedEvent.properties).length).toBeGreaterThan(sourcePropertiesCount)
                        expect(Object.keys(processedEvent.properties).length).toEqual(
                            sourcePropertiesCount + addlPropsCount
                        )
                        expect(processedEvent.properties[testParameter]).toBeDefined()
                        expect(processedEvent.properties[testParameter]).toEqual(testData)
                    } else {
                        expect(processedEvent.properties).toBeDefined()
                    }
                } else {
                    expect(sourceEvent.properties).toBeDefined()
                }
            })
        })
    })

    it('should add 1 property stored as JSON when alwaysJson = true', () => {
        const sourceEvent = buildPageViewEvent('https://posthog.com/test?plugin=1&myUrlParameter=1')

        if (sourceEvent.properties) {
            expect(sourceEvent.properties['myUrlParameter']).not.toBeDefined()

            const sourcePropertiesCount = Object.keys(sourceEvent?.properties).length
            const processedEvent = processEvent(sourceEvent, buildMockMeta({ alwaysJson: 'true' }))

            if (processedEvent.properties) {
                expect(Object.keys(processedEvent.properties).length).toBeGreaterThan(sourcePropertiesCount)
                expect(Object.keys(processedEvent.properties).length).toEqual(sourcePropertiesCount + 1)
                expect(processedEvent.properties['myUrlParameter']).toBeDefined()
                expect(processedEvent.properties.myUrlParameter).toEqual(JSON.stringify(['1']))
            } else {
                expect(processedEvent.properties).toBeDefined()
            }
        } else {
            expect(sourceEvent.properties).toBeDefined()
        }
    })
})
