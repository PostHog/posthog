import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './beehiiv.template'

const PUBLICATION_ID = 'pub_00000000-0000-0000-0000-000000000000'
const EMAIL = 'max+newsletter@posthog.com'
const COLLECTION_URL = `https://api.beehiiv.com/v2/publications/${PUBLICATION_ID}/subscriptions`
const SUBSCRIPTION_URL = `${COLLECTION_URL}/by_email/max%2Bnewsletter%40posthog.com`

const EXPECTED_HEADERS = {
    Authorization: 'Bearer API_KEY',
    'Content-Type': 'application/json',
}

const defaultInputs = {
    apiKey: 'API_KEY',
    publicationId: PUBLICATION_ID,
    email: EMAIL,
    customFields: {
        'First Name': 'Max',
        'Last Name': 'AI',
        Empty: '',
    },
    sendWelcomeEmail: false,
    reactivateExisting: false,
    utmSource: 'posthog',
    utmMedium: 'product',
    utmCampaign: 'newsletter-launch',
    utmTerm: 'product-analytics',
    utmContent: 'upgrade-cta',
    referringSite: 'https://posthog.com/blog',
}

const parseBody = (invocation: any): Record<string, any> => {
    return parseJSON(invocation.queueParameters.body)
}

describe('beehiiv template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('creates a subscriber when no subscription matches the email', async () => {
        const lookupRequest = await tester.invoke(defaultInputs, {})

        expect(lookupRequest.error).toBeUndefined()
        expect(lookupRequest.finished).toBe(false)
        expect(lookupRequest.invocation.queueParameters).toEqual({
            type: 'fetch',
            url: SUBSCRIPTION_URL,
            method: 'GET',
            headers: EXPECTED_HEADERS,
        })

        const createRequest = await tester.invokeFetchResponse(lookupRequest.invocation, {
            status: 404,
            body: { errors: [{ message: 'Subscription not found' }] },
        })

        expect(createRequest.finished).toBe(false)
        expect(createRequest.invocation.queueParameters).toMatchObject({
            type: 'fetch',
            url: COLLECTION_URL,
            method: 'POST',
            headers: EXPECTED_HEADERS,
        })
        expect(parseBody(createRequest.invocation)).toEqual({
            email: EMAIL,
            reactivate_existing: false,
            send_welcome_email: false,
            utm_source: 'posthog',
            utm_medium: 'product',
            utm_campaign: 'newsletter-launch',
            utm_term: 'product-analytics',
            utm_content: 'upgrade-cta',
            referring_site: 'https://posthog.com/blog',
            custom_fields: [
                { name: 'First Name', value: 'Max' },
                { name: 'Last Name', value: 'AI' },
            ],
        })

        const done = await tester.invokeFetchResponse(createRequest.invocation, {
            status: 200,
            body: { data: { id: 'sub_123', email: EMAIL } },
        })

        expect(done.error).toBeUndefined()
        expect(done.finished).toBe(true)
        expect(done.logs.some((log) => log.message.includes(`Successfully created beehiiv subscription ${EMAIL}`))).toBe(
            true
        )
    })

    it('updates custom fields for an existing subscriber', async () => {
        const lookupRequest = await tester.invoke(defaultInputs, {})
        const updateRequest = await tester.invokeFetchResponse(lookupRequest.invocation, {
            status: 200,
            body: { data: { id: 'sub_123', email: EMAIL, status: 'active' } },
        })

        expect(updateRequest.finished).toBe(false)
        expect(updateRequest.invocation.queueParameters).toMatchObject({
            type: 'fetch',
            url: SUBSCRIPTION_URL,
            method: 'PUT',
            headers: EXPECTED_HEADERS,
        })
        expect(parseBody(updateRequest.invocation)).toEqual({
            custom_fields: [
                { name: 'First Name', value: 'Max' },
                { name: 'Last Name', value: 'AI' },
            ],
        })

        const done = await tester.invokeFetchResponse(updateRequest.invocation, {
            status: 200,
            body: { data: { id: 'sub_123', email: EMAIL } },
        })

        expect(done.error).toBeUndefined()
        expect(done.finished).toBe(true)
    })

    it('requests reactivation for existing and newly created subscribers only when enabled', async () => {
        const inputs = { ...defaultInputs, reactivateExisting: true }
        const lookupRequest = await tester.invoke(inputs, {})
        const updateRequest = await tester.invokeFetchResponse(lookupRequest.invocation, {
            status: 200,
            body: { data: { id: 'sub_123', email: EMAIL, status: 'inactive' } },
        })

        expect(parseBody(updateRequest.invocation)).toMatchObject({ unsubscribe: false })

        const missingLookupRequest = await tester.invoke(inputs, {})
        const createRequest = await tester.invokeFetchResponse(missingLookupRequest.invocation, {
            status: 404,
            body: {},
        })
        expect(parseBody(createRequest.invocation)).toMatchObject({ reactivate_existing: true })
    })

    it('skips an existing subscriber when there are no fields to update', async () => {
        const lookupRequest = await tester.invoke({ ...defaultInputs, customFields: {} }, {})
        const response = await tester.invokeFetchResponse(lookupRequest.invocation, {
            status: 200,
            body: { data: { id: 'sub_123', email: EMAIL, status: 'active' } },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeFalsy()
        expect(
            response.logs.some((log) =>
                log.message.includes('Subscription already exists and there are no fields to update. Skipping...')
            )
        ).toBe(true)
    })

    it('skips when email is empty', async () => {
        const response = await tester.invoke({ ...defaultInputs, email: '' }, {})

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeFalsy()
        expect(response.logs.some((log) => log.message.includes('No email set. Skipping...'))).toBe(true)
    })

    it('throws when the subscriber lookup fails', async () => {
        const lookupRequest = await tester.invoke(defaultInputs, {})
        const errorResponse = await tester.invokeFetchResponse(lookupRequest.invocation, {
            status: 401,
            body: { errors: [{ message: 'Unauthorized' }] },
        })

        expect(errorResponse.finished).toBe(true)
        expect(errorResponse.error).toMatch('Error looking up beehiiv subscription (status 401)')
    })

    it('throws when subscriber creation fails', async () => {
        const lookupRequest = await tester.invoke(defaultInputs, {})
        const createRequest = await tester.invokeFetchResponse(lookupRequest.invocation, {
            status: 404,
            body: {},
        })
        const errorResponse = await tester.invokeFetchResponse(createRequest.invocation, {
            status: 400,
            body: { errors: [{ message: 'Invalid email' }] },
        })

        expect(errorResponse.finished).toBe(true)
        expect(errorResponse.error).toMatch('Error creating beehiiv subscription (status 400)')
    })

    it('throws when subscriber update fails', async () => {
        const lookupRequest = await tester.invoke(defaultInputs, {})
        const updateRequest = await tester.invokeFetchResponse(lookupRequest.invocation, {
            status: 200,
            body: { data: { id: 'sub_123', email: EMAIL } },
        })
        const errorResponse = await tester.invokeFetchResponse(updateRequest.invocation, {
            status: 429,
            body: { errors: [{ message: 'Rate limit exceeded' }] },
        })

        expect(errorResponse.finished).toBe(true)
        expect(errorResponse.error).toMatch('Error updating beehiiv subscription (status 429)')
    })
})
