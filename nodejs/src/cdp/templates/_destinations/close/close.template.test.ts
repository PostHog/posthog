import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './close.template'

const SEARCH_URL = 'https://api.close.com/api/v1/data/search/'
const LEAD_URL = 'https://api.close.com/api/v1/lead/'

const EXPECTED_HEADERS = {
    'Content-Type': 'application/json',
    Accept: 'application/json',
    Authorization: `Basic ${Buffer.from('API_KEY:').toString('base64')}`,
}

const EXPECTED_SEARCH_BODY = {
    query: {
        type: 'and',
        queries: [
            { type: 'object_type', object_type: 'contact' },
            {
                type: 'has_related',
                this_object_type: 'contact',
                related_object_type: 'contact_email',
                related_query: {
                    type: 'field_condition',
                    field: { type: 'regular_field', object_type: 'contact_email', field_name: 'email' },
                    condition: { type: 'text', mode: 'phrase', value: 'max@posthog.com' },
                },
            },
        ],
    },
    _fields: { contact: ['id', 'lead_id'] },
    _limit: 1,
}

describe('close template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const defaultInputs = {
        apiKey: 'API_KEY',
        email: 'max@posthog.com',
        leadName: 'PostHog',
        firstName: 'Max',
        lastName: 'AI',
        properties: {
            title: 'Hedgehog in Residence',
        },
        leadProperties: {},
    }

    const parseBody = (invocation: any): Record<string, any> => {
        return parseJSON(invocation.queueParameters.body)
    }

    it('creates a lead when no contact matches', async () => {
        const searchRequest = await tester.invoke(
            { ...defaultInputs, leadProperties: { url: 'https://posthog.com' } },
            {}
        )

        expect(searchRequest.error).toBeUndefined()
        expect(searchRequest.finished).toBe(false)
        const searchParams = searchRequest.invocation.queueParameters as any
        expect(searchParams.url).toBe(SEARCH_URL)
        expect(searchParams.method).toBe('POST')
        expect(searchParams.headers).toEqual(EXPECTED_HEADERS)
        expect(parseBody(searchRequest.invocation)).toEqual(EXPECTED_SEARCH_BODY)

        const createRequest = await tester.invokeFetchResponse(searchRequest.invocation, {
            status: 200,
            body: { data: [], cursor: null },
        })

        expect(createRequest.finished).toBe(false)
        const createParams = createRequest.invocation.queueParameters as any
        expect(createParams.url).toBe(LEAD_URL)
        expect(createParams.method).toBe('POST')
        expect(createParams.headers).toEqual(EXPECTED_HEADERS)
        expect(parseBody(createRequest.invocation)).toEqual({
            name: 'PostHog',
            contacts: [
                {
                    emails: [{ email: 'max@posthog.com', type: 'office' }],
                    name: 'Max AI',
                    title: 'Hedgehog in Residence',
                },
            ],
            url: 'https://posthog.com',
        })

        const done = await tester.invokeFetchResponse(createRequest.invocation, {
            status: 200,
            body: { id: 'lead_123' },
        })
        expect(done.error).toBeUndefined()
        expect(done.finished).toBe(true)
    })

    it('updates the matched contact without touching its emails', async () => {
        const searchRequest = await tester.invoke(defaultInputs, {
            person: { properties: { $geoip_country_name: 'United States', plan: 'pay-as-you-go' } },
        })

        const updateRequest = await tester.invokeFetchResponse(searchRequest.invocation, {
            status: 200,
            body: { data: [{ __object_type: 'contact', id: 'cont_123', lead_id: 'lead_456' }] },
        })

        expect(updateRequest.finished).toBe(false)
        const updateParams = updateRequest.invocation.queueParameters as any
        expect(updateParams.url).toBe('https://api.close.com/api/v1/contact/cont_123/')
        expect(updateParams.method).toBe('PUT')
        expect(updateParams.headers).toEqual(EXPECTED_HEADERS)
        // only the explicitly mapped fields, and no "emails" key - a PUT would
        // replace the contact's existing emails
        expect(parseBody(updateRequest.invocation)).toEqual({
            name: 'Max AI',
            title: 'Hedgehog in Residence',
        })

        const done = await tester.invokeFetchResponse(updateRequest.invocation, {
            status: 200,
            body: { id: 'cont_123' },
        })
        expect(done.error).toBeUndefined()
        expect(done.finished).toBe(true)
    })

    it('omits name when both firstName and lastName are empty', async () => {
        const searchRequest = await tester.invoke({ ...defaultInputs, firstName: '', lastName: '' }, {})

        const createRequest = await tester.invokeFetchResponse(searchRequest.invocation, {
            status: 200,
            body: { data: [] },
        })

        expect(parseBody(createRequest.invocation)).toEqual({
            name: 'PostHog',
            contacts: [
                {
                    emails: [{ email: 'max@posthog.com', type: 'office' }],
                    title: 'Hedgehog in Residence',
                },
            ],
        })
    })

    it('skips the PUT when a contact matches but there is nothing to update', async () => {
        const searchRequest = await tester.invoke({ ...defaultInputs, firstName: '', lastName: '', properties: {} }, {})

        const response = await tester.invokeFetchResponse(searchRequest.invocation, {
            status: 200,
            body: { data: [{ __object_type: 'contact', id: 'cont_123', lead_id: 'lead_456' }] },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeFalsy()
        expect(response.logs.some((log) => log.message.includes('No contact fields to update. Skipping...'))).toBe(true)
    })

    it('JSON-stringifies object-valued property mappings', async () => {
        const searchRequest = await tester.invoke(
            {
                ...defaultInputs,
                properties: {
                    title: 'Hedgehog in Residence',
                    'custom.cf_addresses': [{ city: 'Berlin' }, { city: 'London' }],
                },
            },
            {}
        )

        const createRequest = await tester.invokeFetchResponse(searchRequest.invocation, {
            status: 200,
            body: { data: [] },
        })

        const body = parseBody(createRequest.invocation)
        expect(body.contacts[0]['custom.cf_addresses']).toBe('[{"city":"Berlin"},{"city":"London"}]')
        expect(body.contacts[0].title).toBe('Hedgehog in Residence')
    })

    it('skips when email is empty', async () => {
        const response = await tester.invoke({ ...defaultInputs, email: '' }, {})

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeFalsy()
        expect(response.logs.some((log) => log.message.includes('No email set. Skipping...'))).toBe(true)
    })

    it('throws when the search request fails', async () => {
        const searchRequest = await tester.invoke(defaultInputs, {})

        const errorResponse = await tester.invokeFetchResponse(searchRequest.invocation, {
            status: 400,
            body: { error: 'error' },
        })

        expect(errorResponse.finished).toBe(true)
        expect(errorResponse.error).toMatch('Error from api.close.com (status 400)')
    })

    it('throws when the lead create request fails', async () => {
        const searchRequest = await tester.invoke(defaultInputs, {})

        const createRequest = await tester.invokeFetchResponse(searchRequest.invocation, {
            status: 200,
            body: { data: [] },
        })

        const errorResponse = await tester.invokeFetchResponse(createRequest.invocation, {
            status: 400,
            body: { error: 'error' },
        })

        expect(errorResponse.finished).toBe(true)
        expect(errorResponse.error).toMatch('Error from api.close.com (status 400)')
    })
})
