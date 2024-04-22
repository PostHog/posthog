import {
    CAMPAIGN_PROPERTIES,
    CORE_FILTER_DEFINITIONS_BY_GROUP,
    SESSION_INITIAL_PROPERTIES_ADAPTED_FROM_EVENTS,
} from 'lib/taxonomy'

import { CoreFilterDefinition } from '~/types'

describe('taxonomy', () => {
    describe('event properties', () => {
        it('should have definitions for all campaign properties', () => {
            const eventProperties = Object.keys(CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties)
            for (const property of CAMPAIGN_PROPERTIES) {
                expect(eventProperties).toContain(property)
            }
        })
    })

    describe('person properties', () => {
        // check that initial properties have been set up correctly
        it('should have an $initial_referring_domain property', () => {
            const property: CoreFilterDefinition =
                CORE_FILTER_DEFINITIONS_BY_GROUP.person_properties['$initial_referring_domain']
            expect(property.label).toEqual('Initial Referring Domain')
        })
    })

    describe('session properties', () => {
        const sessionPropertyNames = Object.keys(CORE_FILTER_DEFINITIONS_BY_GROUP.sessions)
        it('should have an $initial_referring_domain property', () => {
            const property: CoreFilterDefinition =
                CORE_FILTER_DEFINITIONS_BY_GROUP.sessions['$initial_referring_domain']
            expect(property.label).toEqual('Initial Referring Domain')
        })
        it(`should have every property in SESSION_PROPERTIES_ADAPTED_FROM_PERSON`, () => {
            for (const property of Array.from(SESSION_INITIAL_PROPERTIES_ADAPTED_FROM_EVENTS.keys())) {
                expect(sessionPropertyNames).toContain('$initial_' + property.replace('$', ''))
            }
        })
    })
})
