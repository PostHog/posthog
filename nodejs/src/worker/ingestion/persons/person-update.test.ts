import { PluginEvent } from '@posthog/plugin-scaffold'

import { personProfileIgnoredPropertiesCounter, personProfileUpdateOutcomeCounter } from './metrics'
import { FILTERED_PERSON_UPDATE_PROPERTIES } from './person-property-utils'
import { applyEventPropertyUpdates, computeEventPropertyUpdates } from './person-update'

jest.mock('./metrics', () => ({
    personProfileUpdateOutcomeCounter: {
        labels: jest.fn().mockReturnValue({
            inc: jest.fn(),
        }),
    },
    personProfileIgnoredPropertiesCounter: {
        labels: jest.fn().mockReturnValue({
            inc: jest.fn(),
        }),
    },
}))

const mockPersonProfileUpdateOutcomeCounter = personProfileUpdateOutcomeCounter as jest.Mocked<
    typeof personProfileUpdateOutcomeCounter
>
const mockPersonProfileIgnoredPropertiesCounter = personProfileIgnoredPropertiesCounter as jest.Mocked<
    typeof personProfileIgnoredPropertiesCounter
>

describe('person-update', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })
    describe('computeEventPropertyUpdates', () => {
        describe('property changes', () => {
            it('should compute updates when custom properties are updated', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { custom_prop: 'new_value' },
                    },
                } as any

                const personProperties = { custom_prop: 'old_value' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ custom_prop: 'new_value' })
                expect(result.shouldForceUpdate).toBe(false)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
                expect(mockPersonProfileUpdateOutcomeCounter.labels({ outcome: 'changed' }).inc).toHaveBeenCalled()
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
            })

            it('should compute updates when properties are unset', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $unset: ['prop_to_remove'],
                    },
                } as any

                const personProperties = { prop_to_remove: 'value', other_prop: 'keep' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toUnset).toEqual(['prop_to_remove'])
                expect(result.shouldForceUpdate).toBe(false)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            })

            it('should compute updates when setting a new property', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { new_prop: 'value' },
                    },
                } as any

                const personProperties = {}

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ new_prop: 'value' })
                expect(result.shouldForceUpdate).toBe(false)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            })

            it('should compute updates when $set_once sets a property that does not exist', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set_once: { first_seen: '2024-01-01' },
                    },
                } as any

                const personProperties = {}

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ first_seen: '2024-01-01' })
                expect(result.shouldForceUpdate).toBe(false)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            })

            it('should compute updates when a new eventToPersonProperty is set (not just updated)', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { $browser: 'Chrome' },
                    },
                } as any

                const personProperties = {}

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ $browser: 'Chrome' })
                expect(result.shouldForceUpdate).toBe(false)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            })
        })

        describe('filtered properties behavior', () => {
            it.each(Array.from(FILTERED_PERSON_UPDATE_PROPERTIES))(
                'should mark "%s" as ignored when updated',
                (propertyName) => {
                    const event: PluginEvent = {
                        event: 'pageview',
                        properties: {
                            $set: { [propertyName]: 'new_value' },
                        },
                    } as any

                    const personProperties = { [propertyName]: 'old_value' }

                    const result = computeEventPropertyUpdates(event, personProperties)

                    expect(result.hasChanges).toBe(true)
                    expect(result.toSet).toEqual({ [propertyName]: 'new_value' })
                    expect(result.shouldForceUpdate).toBe(false)
                    // Filtered properties are marked as ignored
                    expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'ignored' })
                    expect(mockPersonProfileUpdateOutcomeCounter.labels({ outcome: 'ignored' }).inc).toHaveBeenCalled()
                    expect(mockPersonProfileIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({
                        property: propertyName,
                    })
                    expect(
                        mockPersonProfileIgnoredPropertiesCounter.labels({ property: propertyName }).inc
                    ).toHaveBeenCalled()
                }
            )

            it('should accept blocked $geoip_* property updates at event level (filtering happens at batch level)', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { $geoip_latitude: 37.7749 },
                    },
                } as any

                const personProperties = { $geoip_latitude: 40.7128 }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ $geoip_latitude: 37.7749 })
                expect(result.shouldForceUpdate).toBe(false)
                // At event level, blocked geoip properties would be marked as ignored
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'ignored' })
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({
                    property: '$geoip_latitude',
                })
            })

            it('should trigger update when $geoip_country_name changes (allowed geoip property)', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { $geoip_country_name: 'United States' },
                    },
                } as any

                const personProperties = { $geoip_country_name: 'Canada' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ $geoip_country_name: 'United States' })
                expect(result.shouldForceUpdate).toBe(false)
                // $geoip_country_name is allowed so should be marked as changed
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
            })

            it('should trigger update when $geoip_city_name changes (allowed geoip property)', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { $geoip_city_name: 'San Francisco' },
                    },
                } as any

                const personProperties = { $geoip_city_name: 'New York' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ $geoip_city_name: 'San Francisco' })
                expect(result.shouldForceUpdate).toBe(false)
                // $geoip_city_name is allowed so should be marked as changed
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
            })

            it('should update all geoip properties when allowed property ($geoip_country_name) changes alongside blocked ones', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: {
                            $geoip_country_name: 'United States',
                            $geoip_latitude: 37.7749,
                            $geoip_longitude: -122.4194,
                            $geoip_postal_code: '94102',
                        },
                    },
                } as any

                const personProperties = {
                    $geoip_country_name: 'Canada',
                    $geoip_latitude: 43.6532,
                    $geoip_longitude: -79.3832,
                    $geoip_postal_code: 'M5V',
                }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({
                    $geoip_country_name: 'United States',
                    $geoip_latitude: 37.7749,
                    $geoip_longitude: -122.4194,
                    $geoip_postal_code: '94102',
                })
                expect(result.shouldForceUpdate).toBe(false)
                // Since $geoip_country_name is allowed, the update is marked as changed (not ignored)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            })

            it('should accept filtered properties even when mixed with unchanged custom properties', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { $current_url: 'https://example.com/new', custom_prop: 'same_value' },
                    },
                } as any

                const personProperties = { $current_url: 'https://example.com/old', custom_prop: 'same_value' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ $current_url: 'https://example.com/new' })
                expect(result.shouldForceUpdate).toBe(false)
                // $current_url is filtered, so it should be marked as ignored
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'ignored' })
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({
                    property: '$current_url',
                })
            })

            it('should accept multiple filtered properties at event level', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: {
                            $current_url: 'https://example.com/new',
                            $pathname: '/new-path',
                        },
                    },
                } as any

                const personProperties = {
                    $current_url: 'https://example.com/old',
                    $pathname: '/old-path',
                }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.shouldForceUpdate).toBe(false)
                // Filtered properties should be marked as ignored
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'ignored' })
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({
                    property: '$current_url',
                })
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({ property: '$pathname' })
            })
        })

        describe('no changes', () => {
            it('should return no changes when no properties are provided', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {},
                } as any

                const personProperties = { existing_prop: 'value' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(false)
                expect(result.toSet).toEqual({})
                expect(result.toUnset).toEqual([])
                expect(result.shouldForceUpdate).toBe(false)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'no_change' })
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
            })

            it('should return no changes when all properties have the same value', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { custom_prop: 'same_value' },
                    },
                } as any

                const personProperties = { custom_prop: 'same_value' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(false)
                expect(result.toSet).toEqual({})
                expect(result.shouldForceUpdate).toBe(false)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'no_change' })
            })

            it('should return no changes when $set_once property already exists', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set_once: { first_seen: '2024-01-01' },
                    },
                } as any

                const personProperties = { first_seen: '2023-01-01' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(false)
                expect(result.toSet).toEqual({})
                expect(result.shouldForceUpdate).toBe(false)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'no_change' })
            })

            it('should return no changes when trying to unset non-existent property', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $unset: ['non_existent_prop'],
                    },
                } as any

                const personProperties = { other_prop: 'value' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(false)
                expect(result.toUnset).toEqual([])
                expect(result.shouldForceUpdate).toBe(false)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'no_change' })
            })
        })

        describe('person events behavior', () => {
            it('should compute updates for any property on $identify events', () => {
                const event: PluginEvent = {
                    event: '$identify',
                    properties: {
                        $set: { $browser: 'Chrome' },
                    },
                } as any

                const personProperties = { $browser: 'Firefox' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ $browser: 'Chrome' })
                expect(result.shouldForceUpdate).toBe(true)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            })

            it('should compute updates for any property on $set events', () => {
                const event: PluginEvent = {
                    event: '$set',
                    properties: {
                        $set: { utm_source: 'google' },
                    },
                } as any

                const personProperties = { utm_source: 'twitter' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.shouldForceUpdate).toBe(true)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            })

            it('should set shouldForceUpdate to false for non-person events', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { $browser: 'Chrome' },
                    },
                } as any

                const personProperties = { $browser: 'Firefox' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.shouldForceUpdate).toBe(false)
            })
        })

        describe('NO_PERSON_UPDATE_EVENTS behavior', () => {
            it('should skip updates for $exception events regardless of properties', () => {
                const event: PluginEvent = {
                    event: '$exception',
                    properties: {
                        $set: { custom_prop: 'new_value' },
                    },
                } as any

                const personProperties = { custom_prop: 'old_value' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(false)
                expect(result.toSet).toEqual({})
                expect(result.shouldForceUpdate).toBe(false)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'unsupported' })
            })

            it('should skip updates for $$heatmap events regardless of properties', () => {
                const event: PluginEvent = {
                    event: '$$heatmap',
                    properties: {
                        $set: { custom_prop: 'new_value' },
                    },
                } as any

                const personProperties = {}

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(false)
                expect(result.shouldForceUpdate).toBe(false)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'unsupported' })
            })
        })

        describe('mixed scenarios', () => {
            it('should compute updates when both custom and allowed properties change', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { custom_prop: 'new_value', $browser: 'Chrome' },
                    },
                } as any

                const personProperties = { custom_prop: 'old_value', $browser: 'Firefox' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ custom_prop: 'new_value', $browser: 'Chrome' })
                expect(result.shouldForceUpdate).toBe(false)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            })
        })

        describe('updateAllProperties flag enabled', () => {
            it.each(Array.from(FILTERED_PERSON_UPDATE_PROPERTIES))(
                'should trigger update for filtered property "%s" when updateAllProperties is true',
                (propertyName) => {
                    const event: PluginEvent = {
                        event: 'pageview',
                        properties: {
                            $set: { [propertyName]: 'new_value' },
                        },
                    } as any

                    const personProperties = { [propertyName]: 'old_value' }

                    const result = computeEventPropertyUpdates(event, personProperties, true)

                    expect(result.hasChanges).toBe(true)
                    expect(result.toSet).toEqual({ [propertyName]: 'new_value' })
                    expect(result.shouldForceUpdate).toBe(true) // updateAllProperties forces updates
                    // With updateAllProperties=true, no metrics should be tracked
                    expect(mockPersonProfileUpdateOutcomeCounter.labels).not.toHaveBeenCalled()
                    expect(mockPersonProfileIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
                }
            )

            it('should trigger update for $geoip_* properties when updateAllProperties is true', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { $geoip_city_name: 'San Francisco' },
                    },
                } as any

                const personProperties = { $geoip_city_name: 'New York' }

                const result = computeEventPropertyUpdates(event, personProperties, true)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ $geoip_city_name: 'San Francisco' })
                expect(result.shouldForceUpdate).toBe(true) // updateAllProperties forces updates
                // With updateAllProperties=true, no metrics should be tracked
                expect(mockPersonProfileUpdateOutcomeCounter.labels).not.toHaveBeenCalled()
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
            })

            it('should trigger update for multiple allowed properties when updateAllProperties is true', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: {
                            $browser: 'Chrome',
                            $os: 'macOS',
                        },
                    },
                } as any

                const personProperties = {
                    $browser: 'Firefox',
                    $os: 'Windows',
                }

                const result = computeEventPropertyUpdates(event, personProperties, true)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ $browser: 'Chrome', $os: 'macOS' })
                expect(result.shouldForceUpdate).toBe(true) // updateAllProperties forces updates
                // With updateAllProperties=true, no metrics should be tracked
                expect(mockPersonProfileUpdateOutcomeCounter.labels).not.toHaveBeenCalled()
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
            })

            it('should trigger update for mixed allowed and custom properties when updateAllProperties is true', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { $browser: 'Chrome', custom_prop: 'same_value' },
                    },
                } as any

                const personProperties = { $browser: 'Firefox', custom_prop: 'same_value' }

                const result = computeEventPropertyUpdates(event, personProperties, true)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ $browser: 'Chrome' })
                expect(result.shouldForceUpdate).toBe(true) // updateAllProperties forces updates
                // With updateAllProperties=true, no metrics should be tracked
                expect(mockPersonProfileUpdateOutcomeCounter.labels).not.toHaveBeenCalled()
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
            })

            it('should trigger update for mixed $geoip_* and allowed properties when updateAllProperties is true', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: {
                            $browser: 'Chrome',
                            $geoip_city_name: 'San Francisco',
                            $geoip_country_code: 'US',
                        },
                    },
                } as any

                const personProperties = {
                    $browser: 'Firefox',
                    $geoip_city_name: 'New York',
                    $geoip_country_code: 'CA',
                }

                const result = computeEventPropertyUpdates(event, personProperties, true)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({
                    $browser: 'Chrome',
                    $geoip_city_name: 'San Francisco',
                    $geoip_country_code: 'US',
                })
                expect(result.shouldForceUpdate).toBe(true) // updateAllProperties forces updates
                // With updateAllProperties=true, no metrics should be tracked
                expect(mockPersonProfileUpdateOutcomeCounter.labels).not.toHaveBeenCalled()
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
            })

            it('should not change behavior for NO_PERSON_UPDATE_EVENTS when updateAllProperties is true', () => {
                const event: PluginEvent = {
                    event: '$exception',
                    properties: {
                        $set: { $browser: 'Chrome' },
                    },
                } as any

                const personProperties = { $browser: 'Firefox' }

                const result = computeEventPropertyUpdates(event, personProperties, true)

                // NO_PERSON_UPDATE_EVENTS should still be skipped regardless of flag
                expect(result.hasChanges).toBe(false)
                expect(result.toSet).toEqual({})
                expect(result.shouldForceUpdate).toBe(false)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'unsupported' })
            })
        })
    })

    describe('applyEventPropertyUpdates', () => {
        it('should apply property updates and return updated person', () => {
            const propertyUpdates = {
                hasChanges: true,
                toSet: { name: 'John', email: 'john@example.com' },
                toUnset: ['old_prop'],
                shouldForceUpdate: false,
            }

            const person = {
                id: '1',
                team_id: 123,
                uuid: 'test-uuid',
                properties: { old_prop: 'value', name: 'Jane' },
                created_at: new Date(),
                version: 0,
                is_identified: false,
            }

            const [updatedPerson, wasUpdated] = applyEventPropertyUpdates(propertyUpdates, person as any)

            expect(wasUpdated).toBe(true)
            expect(updatedPerson.properties).toEqual({ name: 'John', email: 'john@example.com' })
            expect(updatedPerson.properties.old_prop).toBeUndefined()
        })

        it('should not modify original person object', () => {
            const propertyUpdates = {
                hasChanges: true,
                toSet: { name: 'John' },
                toUnset: [],
                shouldForceUpdate: false,
            }

            const person = {
                id: '1',
                team_id: 123,
                uuid: 'test-uuid',
                properties: { name: 'Jane' },
                created_at: new Date(),
                version: 0,
                is_identified: false,
            }

            const [updatedPerson, _] = applyEventPropertyUpdates(propertyUpdates, person as any)

            expect(person.properties.name).toBe('Jane')
            expect(updatedPerson.properties.name).toBe('John')
            expect(person).not.toBe(updatedPerson)
        })

        it('should return false for wasUpdated when no actual changes occur', () => {
            const propertyUpdates = {
                hasChanges: false,
                toSet: { name: 'John' },
                toUnset: [],
                shouldForceUpdate: false,
            }

            const person = {
                id: '1',
                team_id: 123,
                uuid: 'test-uuid',
                properties: { name: 'John' },
                created_at: new Date(),
                version: 0,
                is_identified: false,
            }

            const [_, wasUpdated] = applyEventPropertyUpdates(propertyUpdates, person as any)

            expect(wasUpdated).toBe(false)
        })
    })
})
