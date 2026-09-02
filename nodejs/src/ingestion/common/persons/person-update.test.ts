import { DateTime } from 'luxon'

import { personProfileIgnoredPropertiesCounter, personProfileUpdateOutcomeCounter } from '~/common/persons/metrics'
import { FILTERED_PERSON_UPDATE_PROPERTIES } from '~/common/persons/person-property-utils'
import { PluginEvent } from '~/plugin-scaffold'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson } from '~/types'

import {
    EventOps,
    applyEventPropertyUpdates,
    computeOpsScalarUpdates,
    extractEventOps,
    foldOps,
    refineEventOps,
} from './person-update'

// The scenarios below exercise the extract → refine pair end to end, the
// same composition the Postgres store runs per event.
const computeEventPropertyUpdates = (event: PluginEvent, personProperties: Properties, updateAllProperties = false) =>
    refineEventOps(extractEventOps(event, updateAllProperties), personProperties, updateAllProperties)

jest.mock('~/common/persons/metrics', () => ({
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

            it('surfaces the filtered-only verdict for store-side suppression', () => {
                const filteredOnly = computeEventPropertyUpdates(
                    { event: 'pageview', properties: { $set: { $browser: 'Chrome' } } } as any,
                    { $browser: 'Firefox' }
                )
                expect(filteredOnly.hasChanges).toBe(true)
                expect(filteredOnly.hasNonFilteredChanges).toBe(false)

                const newKey = computeEventPropertyUpdates(
                    { event: 'pageview', properties: { $set: { $browser: 'Chrome' } } } as any,
                    {}
                )
                expect(newKey.hasNonFilteredChanges).toBe(true)
            })

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
                hasNonFilteredChanges: true,
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
                hasNonFilteredChanges: true,
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
                hasNonFilteredChanges: false,
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

    describe('computeOpsScalarUpdates', () => {
        const personState = (overrides: Partial<InternalPerson>): InternalPerson =>
            ({ properties: {}, is_identified: false, last_seen_at: null, ...overrides }) as unknown as InternalPerson

        const ops = (overrides: Partial<EventOps>): EventOps => ({
            set: {},
            setOnce: {},
            unset: [],
            denied: false,
            shouldForceUpdate: false,
            eventName: '$set',
            ...overrides,
        })

        it.each([
            ['identifies an unidentified person', { isIdentified: true }, {}, { is_identified: true }],
            ['does not re-identify an identified person', { isIdentified: true }, { is_identified: true }, {}],
            ['never reverts identification', {}, { is_identified: true }, {}],
        ] as [string, Partial<EventOps>, Partial<InternalPerson>, Partial<InternalPerson>][])(
            '%s',
            (_label, opOverrides, personOverrides, expected) => {
                expect(computeOpsScalarUpdates(ops(opOverrides), personState(personOverrides))).toEqual(expected)
            }
        )

        it('advances last_seen_at only forward', () => {
            const older = DateTime.fromMillis(3_600_000, { zone: 'utc' })
            const newer = DateTime.fromMillis(7_200_000, { zone: 'utc' })
            const seenAt = personState({ last_seen_at: older } as unknown as Partial<InternalPerson>)

            expect(computeOpsScalarUpdates(ops({ lastSeenAtMs: 7_200_000 }), seenAt)).toEqual({
                last_seen_at: newer,
            })
            const current = personState({ last_seen_at: newer } as unknown as Partial<InternalPerson>)
            expect(computeOpsScalarUpdates(ops({ lastSeenAtMs: 3_600_000 }), current)).toEqual({})
        })

        it('denied ops still contribute their scalars', () => {
            // The denylist gates property writes only; both stores and
            // the leader advance identity and last-seen regardless.
            const updates = computeOpsScalarUpdates(
                ops({ denied: true, isIdentified: true, lastSeenAtMs: 3_600_000 }),
                personState({})
            )
            expect(updates.is_identified).toBe(true)
            expect(updates.last_seen_at?.toMillis()).toBe(3_600_000)
        })
    })

    describe('fold equivalence', () => {
        // Deterministic PRNG (mulberry32): the sweep must reproduce
        // identically on every run.
        const mulberry32 = (seed: number) => (): number => {
            seed = (seed + 0x6d2b79f5) | 0
            let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
            t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296
        }

        const KEYS = ['k1', 'k2', 'k3']

        const randomProps = (rand: () => number): Record<string, string> =>
            Object.fromEntries(KEYS.filter(() => rand() < 0.4).map((k) => [k, `v${Math.floor(rand() * 4)}`]))

        const randomOps = (rand: () => number): EventOps => {
            const set = randomProps(rand)
            const setOnce = Object.fromEntries(Object.entries(randomProps(rand)).filter(([k]) => !(k in set)))
            return {
                set,
                // extractEventOps guarantees an event's set_once keys are
                // not among its set keys; the generator upholds the same
                // invariant so the sweep covers reachable shapes only.
                setOnce,
                unset: KEYS.filter(() => rand() < 0.25),
                denied: false,
                shouldForceUpdate: false,
                isIdentified: rand() < 0.2 ? true : undefined,
                lastSeenAtMs: rand() < 0.3 ? 3_600_000 * (1 + Math.floor(rand() * 3)) : undefined,
                eventName: '$set',
            }
        }

        const personWith = (properties: Record<string, string>): InternalPerson =>
            ({ properties, is_identified: false }) as unknown as InternalPerson

        // This is the algebra the personhog store stakes its correctness
        // on: folding a person's ops across a batch and refining the
        // fold once must land on the same state as refining each event
        // sequentially against evolving state, for every interleaving of
        // set, set_once, and unset over shared keys.
        it('folding into segments then refining each matches refining every op sequentially', () => {
            const rand = mulberry32(20260807)
            let segmentedRounds = 0
            for (let round = 0; round < 500; round++) {
                const baseProps = randomProps(rand)
                const opsList = Array.from({ length: 2 + Math.floor(rand() * 4) }, () => randomOps(rand))

                let sequential = personWith({ ...baseProps })
                let seqIdentified = false
                let seqLastSeen: number | null = null
                for (const o of opsList) {
                    const refined = refineEventOps(o, sequential.properties, false)
                    ;[sequential] = applyEventPropertyUpdates(refined, sequential)
                    seqIdentified = seqIdentified || o.isIdentified === true
                    if (o.lastSeenAtMs !== undefined) {
                        seqLastSeen = Math.max(seqLastSeen ?? 0, o.lastSeenAtMs)
                    }
                }

                // Exactly the store's lane discipline: fold onto the last
                // segment, cut a new one when the composition is not
                // representable, ship segments in order.
                const segments: EventOps[] = [opsList[0]]
                for (const o of opsList.slice(1)) {
                    const folded = foldOps(segments[segments.length - 1], o)
                    if (folded === null) {
                        segments.push(o)
                    } else {
                        segments[segments.length - 1] = folded
                    }
                }
                if (segments.length > 1) {
                    segmentedRounds++
                }

                let candidate = personWith({ ...baseProps })
                let candIdentified = false
                let candLastSeen: number | null = null
                for (const seg of segments) {
                    const refined = refineEventOps(seg, candidate.properties, false)
                    ;[candidate] = applyEventPropertyUpdates(refined, candidate)
                    candIdentified = candIdentified || seg.isIdentified === true
                    if (seg.lastSeenAtMs !== undefined) {
                        candLastSeen = Math.max(candLastSeen ?? 0, seg.lastSeenAtMs)
                    }
                }

                const context = { round, baseProps, opsList }
                expect({ ...context, out: candidate.properties }).toEqual({
                    ...context,
                    out: sequential.properties,
                })
                expect(candIdentified).toBe(seqIdentified)
                expect(candLastSeen).toBe(seqLastSeen)
            }
            // The sweep must actually exercise the segmentation path, or
            // the null branch is dead weight it never validates.
            expect(segmentedRounds).toBeGreaterThan(0)
        })
    })

    describe('foldOps', () => {
        const eventOps = (properties: Record<string, unknown>, event = '$set') =>
            extractEventOps({ event, properties } as any)

        const fold = (existing: EventOps, incoming: EventOps): EventOps => {
            const folded = foldOps(existing, incoming)
            expect(folded).not.toBeNull()
            return folded!
        }

        it('preserves sequential semantics per key across folded events', () => {
            // set shadows a pending set_once; among set_onces the first
            // wins; an unset clears both lanes; a set_once after an unset
            // becomes an unconditional set.
            let acc = eventOps({ $set_once: { plan: 'first', keep: 'kept' } })
            acc = fold(acc, eventOps({ $set: { plan: 'shadowing' }, $set_once: { keep: 'second-loses' } }))
            acc = fold(acc, eventOps({ $unset: ['gone', 'revived'] }))
            acc = fold(acc, eventOps({ $set_once: { revived: 'promoted' } }))

            expect(acc.set).toEqual({ plan: 'shadowing', revived: 'promoted' })
            expect(acc.setOnce).toEqual({ keep: 'kept' })
            expect(acc.unset).toEqual(['gone'])
        })

        it('a later set supersedes a pending unset for its key', () => {
            const acc = fold(eventOps({ $unset: ['a'] }), eventOps({ $set: { a: 'back' } }))
            expect(acc.set).toEqual({ a: 'back' })
            expect(acc.unset).toEqual([])
        })

        it('a same-event value and unset pair rides the fold whole', () => {
            // The pair's outcome is snapshot-dependent (present resolves
            // to gone, absent to the value), so both lanes must survive
            // for refinement to decide — dropping either loses one branch.
            const acc = fold(eventOps({ $set: { other: 'x' } }), eventOps({ $set_once: { k: 'v' }, $unset: ['k'] }))
            expect(acc.setOnce).toEqual({ k: 'v' })
            expect(acc.unset).toEqual(['k'])
        })

        it('a pair over pending value state resolves to a plain unset', () => {
            // Pending state guarantees the key present at refinement, so
            // the pair's present branch (gone) is the only reachable one.
            const acc = fold(eventOps({ $set: { k: 'pending' } }), eventOps({ $set_once: { k: 'v' }, $unset: ['k'] }))
            expect(acc.set).toEqual({})
            expect(acc.setOnce).toEqual({})
            expect(acc.unset).toEqual(['k'])
        })

        it.each([
            ['a set_once', { $set_once: { k: 'later' } }],
            ['another pair', { $set_once: { k: 'later' }, $unset: ['k'] }],
        ])('%s over a pending pair cuts a segment', (_label, later) => {
            // "Present resolves one way, absent another with a different
            // value" has no lane representation; the caller must ship the
            // accumulated ops and fold onward from the incoming event.
            const pair = eventOps({ $set_once: { k: 'v' }, $unset: ['k'] })
            expect(foldOps(pair, eventOps(later))).toBeNull()
        })

        it('identity ORs and last-seen max-merges, mirroring the leader', () => {
            const first = eventOps({})
            first.isIdentified = true
            first.lastSeenAtMs = 7_200_000
            const second = eventOps({})
            second.lastSeenAtMs = 3_600_000

            const acc = fold(first, second)
            expect(acc.isIdentified).toBe(true)
            expect(acc.lastSeenAtMs).toEqual(7_200_000)
        })

        it('denied events contribute nothing in either direction', () => {
            const denied = eventOps({ $set: { a: '1' } }, '$exception')
            const real = eventOps({ $set: { b: '2' } })
            expect(foldOps(real, denied)).toEqual(real)
            expect(foldOps(denied, real)).toEqual(real)
        })

        describe('exhaustive single-key transition table', () => {
            const K = 'k'
            type Shape = Record<string, unknown> | null
            // Every reachable accumulated state, named by the ops that
            // produce it, and every per-key shape one event can carry.
            const STATES: [string, Shape][] = [
                ['empty', null],
                ['pending set', { $set: { [K]: 'p-set' } }],
                ['pending set_once', { $set_once: { [K]: 'p-once' } }],
                ['pending unset', { $unset: [K] }],
                ['pending set pair', { $set: { [K]: 'p-pair' }, $unset: [K] }],
                ['pending set_once pair', { $set_once: { [K]: 'p-pair' }, $unset: [K] }],
            ]
            const INCOMING: [string, Record<string, unknown>][] = [
                ['set', { $set: { [K]: 'i-set' } }],
                ['set_once', { $set_once: { [K]: 'i-once' } }],
                ['unset', { $unset: [K] }],
                ['set pair', { $set: { [K]: 'i-pair' }, $unset: [K] }],
                ['set_once pair', { $set_once: { [K]: 'i-pair' }, $unset: [K] }],
            ]
            // The pair state is the one place composition can lose
            // information, and only under an incoming op that is itself
            // snapshot-dependent for the key.
            const SEGMENTS = new Set(
                ['pending set pair', 'pending set_once pair'].flatMap((s) =>
                    ['set_once', 'set pair', 'set_once pair'].map((i) => `${s}|${i}`)
                )
            )
            const CASES = STATES.flatMap(([stateLabel, stateProps]) =>
                INCOMING.flatMap(([inLabel, inProps]) =>
                    [
                        ['absent', {}],
                        ['present', { [K]: 'existing' }],
                    ].map(([snapLabel, snapshot]) => [stateLabel, inLabel, snapLabel, stateProps, inProps, snapshot])
                )
            ) as [string, string, string, Shape, Record<string, unknown>, Properties][]

            const applySequentially = (events: Record<string, unknown>[], snapshot: Properties): Properties => {
                let personState = { properties: { ...snapshot }, is_identified: false } as unknown as InternalPerson
                for (const properties of events) {
                    const refined = refineEventOps(eventOps(properties), personState.properties, false)
                    ;[personState] = applyEventPropertyUpdates(refined, personState)
                }
                return personState.properties
            }

            it.each(CASES)(
                '%s then %s over %s key: fold matches sequential refinement',
                (stateLabel, inLabel, _snapLabel, stateProps, inProps, snapshot) => {
                    const events = stateProps === null ? [inProps] : [stateProps, inProps]
                    const sequential = applySequentially(events, snapshot)

                    const accumulated = eventOps(stateProps ?? {})
                    const folded = foldOps(accumulated, eventOps(inProps))

                    if (folded === null) {
                        expect(SEGMENTS.has(`${stateLabel}|${inLabel}`)).toBe(true)
                        // A cut segment ships each side as its own leader
                        // call, which is the sequential application above
                        // by construction — nothing further to assert.
                        return
                    }
                    expect(SEGMENTS.has(`${stateLabel}|${inLabel}`)).toBe(false)
                    let personState = { properties: { ...snapshot }, is_identified: false } as unknown as InternalPerson
                    const refined = refineEventOps(folded, personState.properties, false)
                    ;[personState] = applyEventPropertyUpdates(refined, personState)
                    expect(personState.properties).toEqual(sequential)
                }
            )
        })

        it('a denied event still contributes its identity and last-seen scalars', () => {
            // The denylist gates property writes only; both stores and
            // the leader advance the scalars regardless of event kind.
            const denied = eventOps({ $set: { a: '1' } }, '$exception')
            denied.lastSeenAtMs = 7_200_000
            denied.isIdentified = true
            const real = eventOps({ $set: { b: '2' } })

            const acc = fold(real, denied)
            expect(acc.set).toEqual(real.set)
            expect(acc.isIdentified).toBe(true)
            expect(acc.lastSeenAtMs).toBe(7_200_000)
        })
    })
})
