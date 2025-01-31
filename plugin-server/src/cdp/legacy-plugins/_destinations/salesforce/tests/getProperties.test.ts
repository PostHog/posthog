import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { getProperties } from '../index'

describe('filtering by property allow list', () => {
    describe('filtering', () => {
        it('does not filter if there is no allow list', () => {
            const properties = { a: 'a', b: 'b' }
            const filteredProperties = getProperties({ properties } as unknown as ProcessedPluginEvent, '')
            expect(filteredProperties).toEqual(properties)
        })

        it('does filter if there is an allow list', () => {
            const properties = { a: 'a', b: 'b', c: 'c' }
            const filteredProperties = getProperties({ properties } as unknown as ProcessedPluginEvent, 'a,c')
            expect(filteredProperties).toEqual({ a: 'a', c: 'c' })
        })

        it('copes with spaces in the config', () => {
            const properties = { a: 'a', b: 'b', c: 'c' }
            const filteredProperties = getProperties({ properties } as unknown as ProcessedPluginEvent, 'a,   c')
            expect(filteredProperties).toEqual({ a: 'a', c: 'c' })
        })

        it('converts properties using field mappings', () => {
            const properties = { email: 'a', b: 'b', surname: 'c', d: 'e' }
            const filteredProperties = getProperties(
                { properties } as unknown as ProcessedPluginEvent,
                'email,surname,d',
                {
                    email: 'Email',
                    surname: 'LastName',
                }
            )
            expect(filteredProperties).toEqual({ Email: 'a', LastName: 'c', d: 'e' })
        })

        it('can handle nested properties', () => {
            const properties = { name: 'a@b.com', person_properties: { middle: { bottom: 'val' }, surname: 'Smith' } }
            const filteredProperties = getProperties(
                { properties } as unknown as ProcessedPluginEvent,
                'person_properties.surname,name',
                {
                    name: 'Name',
                    'person_properties.surname': 'LastName',
                }
            )

            expect(filteredProperties).toEqual({
                Name: 'a@b.com',
                LastName: 'Smith',
            })
        })

        it('can handle deeply nested properties', () => {
            const properties = { name: 'a@b.com', person_properties: { middle: { bottom: 'val' }, surname: 'Smith' } }
            const filteredProperties = getProperties(
                { properties } as unknown as ProcessedPluginEvent,
                'person_properties.middle.bottom,name',
                {
                    name: 'Name',
                    'person_properties.surname': 'LastName',
                    'person_properties.middle.bottom': 'MiddleBottom',
                }
            )

            expect(filteredProperties).toEqual({
                Name: 'a@b.com',
                MiddleBottom: 'val',
            })
        })

        it('maps fields when there are no properties to include provided', () => {
            const properties = { name: 'a@b.com', another: 'value' }
            const filteredProperties = getProperties({ properties } as unknown as ProcessedPluginEvent, '     ', {
                name: 'Name',
                // redundant mapping is safely ignored
                'person_properties.surname': 'LastName',
            })

            expect(filteredProperties).toEqual({
                Name: 'a@b.com',
                another: 'value',
            })
        })
    })
})
