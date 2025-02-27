import { LegacyDestinationPluginMeta } from '../../types'
import { onEvent, setupPlugin } from './index'

describe('sendgrid', () => {
    const mockFetch = jest.fn()
    let meta: LegacyDestinationPluginMeta = {} as any

    beforeEach(() => {
        meta = {
            config: {
                sendgridApiKey: 'SENDGRID_API_KEY',
            },
            global: {},
            fetch: mockFetch,
        } as any

        mockFetch.mockClear()
        mockFetch.mockImplementation((url) => ({
            json: () =>
                url.includes('/field_definitions')
                    ? {
                          custom_fields: [
                              { id: 'field1', name: 'my_prop1' },
                              { id: 'field2', name: 'my_prop2' },
                          ],
                      }
                    : {},
            status: 200,
        }))
    })

    test('setupPlugin uses sendgridApiKey', async () => {
        expect(mockFetch).toHaveBeenCalledTimes(0)

        await setupPlugin(meta)
        expect(mockFetch).toHaveBeenCalledTimes(1)
        expect(mockFetch).toHaveBeenCalledWith('https://api.sendgrid.com/v3/marketing/field_definitions', {
            method: 'GET',
            headers: {
                Authorization: 'Bearer SENDGRID_API_KEY',
            },
        })
    })

    test('setupPlugin fails if bad customFields format', async () => {
        meta = {
            config: {
                sendgridApiKey: 'SENDGRID_API_KEY',
                customFields: 'asf=asdf=asf',
            },
            fetch: mockFetch,
        } as any

        await expect(setupPlugin(meta)).rejects.toThrow()
    })

    test('setupPlugin fails if custom field not defined in Sendgrid', async () => {
        meta = {
            config: {
                sendgridApiKey: 'SENDGRID_API_KEY',
                customFields: 'not_defined_custom_field',
            },
            fetch: mockFetch,
        } as any

        await expect(setupPlugin(meta)).rejects.toThrow()
    })

    test('setupPlugin to accept valid customFields and parse them correctly', async () => {
        meta = {
            config: {
                sendgridApiKey: 'SENDGRID_API_KEY',
                customFields: 'myProp1=my_prop1,my_prop2',
            },
            global: {},
            fetch: mockFetch,
        } as any

        await setupPlugin(meta)
        expect(meta.global.customFieldsMap).toStrictEqual({
            myProp1: 'field1',
            my_prop2: 'field2',
        })
    })

    test('onEvent to send contacts with custom fields', async () => {
        meta = {
            config: {
                sendgridApiKey: 'SENDGRID_API_KEY',
                customFields: 'myProp1=my_prop1,my_prop2',
            },
            global: {},
            fetch: mockFetch,
        } as any

        const event = {
            event: '$identify',
            distinct_id: 'user0@example.org',
            $set: {
                lastName: 'User0',
            },
        }
        const event2 = {
            event: '$identify',
            $set: {
                email: 'user1@example.org',
                lastName: 'User1',
                myProp1: 'foo',
            },
        }

        expect(mockFetch).toHaveBeenCalledTimes(0)
        await setupPlugin(meta)
        expect(mockFetch).toHaveBeenCalledTimes(1)
        await onEvent(event as any, meta)
        expect(mockFetch).toHaveBeenCalledTimes(2)
        expect(mockFetch).toHaveBeenCalledWith('https://api.sendgrid.com/v3/marketing/contacts', {
            method: 'PUT',
            headers: {
                Authorization: 'Bearer SENDGRID_API_KEY',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                contacts: [
                    {
                        email: 'user0@example.org',
                        last_name: 'User0',
                        custom_fields: {},
                    },
                ],
            }),
        })
        await onEvent(event2 as any, meta)
        expect(mockFetch).toHaveBeenCalledTimes(3)
        expect(mockFetch).toHaveBeenCalledWith('https://api.sendgrid.com/v3/marketing/contacts', {
            method: 'PUT',
            headers: {
                Authorization: 'Bearer SENDGRID_API_KEY',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                contacts: [
                    {
                        email: 'user1@example.org',
                        last_name: 'User1',
                        custom_fields: {
                            field1: 'foo',
                        },
                    },
                ],
            }),
        })
    })
})
