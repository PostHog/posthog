import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './hubspot.template'

const defaultInputs = {
    oauth: {
        access_token: 'access-token',
    },
    companyId: 'company-123',
    properties: {
        name: 'Test Company',
        domain: 'test.com',
        description: 'A test company',
    },
}

const defaultGlobals = {}

describe('hubspot template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    afterEach(() => {
        tester.afterEach()
    })

    it('should update existing company', async () => {
        const response = await tester.invoke(defaultInputs, defaultGlobals)

        expect(response.logs).toMatchInlineSnapshot(`[]`)
        expect(response.error).toMatchInlineSnapshot(`undefined`)
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"properties":{"posthog_group_id":"company-123","name":"Test Company","domain":"test.com","description":"A test company"}}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
              },
              "method": "PATCH",
              "type": "fetch",
              "url": "https://api.hubapi.com/crm/v3/objects/companies/company-123?idProperty=posthog_group_id",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { id: 'hubspot-company-id' },
        })

        expect(fetchResponse.logs).toMatchInlineSnapshot(`
            [
              {
                "level": "info",
                "message": "Successfully updated company company-123",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "Function completed in [REPLACED]",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
            ]
        `)
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toEqual(true)
    })

    it('should create company when it does not exist and unique property exists', async () => {
        const response = await tester.invoke(defaultInputs, defaultGlobals)

        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"properties":{"posthog_group_id":"company-123","name":"Test Company","domain":"test.com","description":"A test company"}}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
              },
              "method": "PATCH",
              "type": "fetch",
              "url": "https://api.hubapi.com/crm/v3/objects/companies/company-123?idProperty=posthog_group_id",
            }
        `)

        const patchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 404,
            body: { message: 'Company not found' },
        })

        expect(patchResponse.finished).toEqual(false)
        expect(patchResponse.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"name":"posthog_group_id","label":"PostHog Group ID","description":"Unique Property to map PostHog Group ID with a HubSpot Company Object","groupName":"companyinformation","type":"string","fieldType":"text","hidden":true,"displayOrder":-1,"hasUniqueValue":true,"formField":false}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://api.hubapi.com/crm/v3/properties/companies",
            }
        `)

        const propertyResponse = await tester.invokeFetchResponse(patchResponse.invocation, {
            status: 409,
            body: { message: 'Property already exists' },
        })

        expect(propertyResponse.finished).toEqual(false)
        expect(propertyResponse.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"properties":{"posthog_group_id":"company-123","name":"Test Company","domain":"test.com","description":"A test company"}}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://api.hubapi.com/crm/v3/objects/companies",
            }
        `)

        const postResponse = await tester.invokeFetchResponse(propertyResponse.invocation, {
            status: 201,
            body: { id: 'new-hubspot-company-id' },
        })

        expect(postResponse.logs).toMatchInlineSnapshot(`
            [
              {
                "level": "info",
                "message": "Successfully created company company-123",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "Function completed in [REPLACED]",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
            ]
        `)
        expect(postResponse.error).toBeUndefined()
        expect(postResponse.finished).toEqual(true)
    })

    it('should create unique property and company when both do not exist', async () => {
        const response = await tester.invoke(defaultInputs, defaultGlobals)

        const patchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 404,
            body: { message: 'Company not found' },
        })

        expect(patchResponse.finished).toEqual(false)
        expect(patchResponse.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"name":"posthog_group_id","label":"PostHog Group ID","description":"Unique Property to map PostHog Group ID with a HubSpot Company Object","groupName":"companyinformation","type":"string","fieldType":"text","hidden":true,"displayOrder":-1,"hasUniqueValue":true,"formField":false}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://api.hubapi.com/crm/v3/properties/companies",
            }
        `)

        const propertyResponse = await tester.invokeFetchResponse(patchResponse.invocation, {
            status: 201,
            body: { name: 'posthog_group_id' },
        })

        expect(propertyResponse.finished).toEqual(false)
        expect(propertyResponse.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"properties":{"posthog_group_id":"company-123","name":"Test Company","domain":"test.com","description":"A test company"}}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://api.hubapi.com/crm/v3/objects/companies",
            }
        `)

        const postResponse = await tester.invokeFetchResponse(propertyResponse.invocation, {
            status: 201,
            body: { id: 'new-hubspot-company-id' },
        })

        expect(tester.logsForSnapshot(postResponse.logs)).toMatchInlineSnapshot(`
            [
              {
                "level": "info",
                "message": "Successfully created company company-123",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "Function completed in [REPLACED]",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
            ]
        `)
        expect(postResponse.error).toMatchInlineSnapshot(`undefined`)
        expect(postResponse.finished).toEqual(true)
    })

    it('should skip if companyId is empty', async () => {
        const inputs = { ...defaultInputs, companyId: '' }
        const response = await tester.invoke(inputs, defaultGlobals)

        expect(tester.logsForSnapshot(response.logs)).toMatchInlineSnapshot(`
            [
              {
                "level": "info",
                "message": "\`companyId\` input is empty. Skipping...",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "Function completed in [REPLACED]",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
            ]
        `)
        expect(response.error).toMatchInlineSnapshot(`undefined`)
        expect(response.finished).toEqual(true)
    })
})
