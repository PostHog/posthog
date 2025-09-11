import { onEvent, setupPlugin } from './index'

const { getMeta, resetMeta } = require('@posthog/plugin-scaffold/test/utils.js')

describe('sendgrid', () => {
    const mockFetch = jest.fn()

    beforeEach(() => {
        resetMeta({
            config: {
                sendgridApiKey: 'SENDGRID_API_KEY',
            },
            global: global,
            fetch: mockFetch,
        })

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

        await setupPlugin(getMeta())
        expect(mockFetch).toHaveBeenCalledTimes(1)
        expect(mockFetch).toHaveBeenCalledWith('https://api.sendgrid.com/v3/marketing/field_definitions', {
            method: 'GET',
            headers: {
                Authorization: 'Bearer SENDGRID_API_KEY',
            },
        })
    })

    test('setupPlugin fails if bad customFields format', async () => {
        resetMeta({
            config: {
                sendgridApiKey: 'SENDGRID_API_KEY',
                customFields: 'asf=asdf=asf',
            },
            fetch: mockFetch,
        })

        await expect(setupPlugin(getMeta())).rejects.toThrow()
    })

    test('setupPlugin fails if custom field not defined in Sendgrid', async () => {
        resetMeta({
            config: {
                sendgridApiKey: 'SENDGRID_API_KEY',
                customFields: 'not_defined_custom_field',
            },
            fetch: mockFetch,
        })

        await expect(setupPlugin(getMeta())).rejects.toThrow()
    })

    test('setupPlugin to accept valid customFields and parse them correctly', async () => {
        resetMeta({
            config: {
                sendgridApiKey: 'SENDGRID_API_KEY',
                customFields: 'myProp1=my_prop1,my_prop2',
            },
            fetch: mockFetch,
        })

        await setupPlugin(getMeta())
        const { global } = getMeta()
        expect(global.customFieldsMap).toStrictEqual({
            myProp1: 'field1',
            my_prop2: 'field2',
        })
    })

    test('onEvent to send contacts with custom fields', async () => {
        resetMeta({
            config: {
                sendgridApiKey: 'SENDGRID_API_KEY',
                customFields: 'myProp1=my_prop1,my_prop2',
            },
            fetch: mockFetch,
        })

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
        await setupPlugin(getMeta())
        expect(mockFetch).toHaveBeenCalledTimes(1)
        await onEvent(event as any, getMeta())
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
        await onEvent(event2 as any, getMeta())
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
