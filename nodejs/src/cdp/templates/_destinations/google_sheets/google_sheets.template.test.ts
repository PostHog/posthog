import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './google_sheets.template'

const defaultInputs = {
    oauth: {
        access_token: 'access-token',
    },
    spreadsheet_id: 'spreadsheet-id',
}

const defaultGlobals = {
    event: {
        event: 'event-name',
        timestamp: '2024-01-01T00:00:00Z',
    },
}

describe('google sheets template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    afterEach(() => {
        tester.afterEach()
    })

    it('should invoke the function', async () => {
        const response = await tester.invoke(defaultInputs, defaultGlobals)

        expect(response.logs).toMatchInlineSnapshot(`[]`)
        expect(response.error).toMatchInlineSnapshot(`undefined`)
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"data":{"range":"Sheet1!A1:A","values":[["timestamp","event_name"]]},"valueInputOption":"RAW"}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://sheets.googleapis.com/v4/spreadsheets/spreadsheet-id/values:batchUpdate",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { status: 'OK' },
        })

        expect(fetchResponse.logs).toMatchInlineSnapshot(`[]`)
        expect(fetchResponse.error).toMatchInlineSnapshot(`undefined`)
        expect(fetchResponse.finished).toEqual(false)
        expect(fetchResponse.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"values":[["2024-01-01T00:00:00Z","event-name"]]}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://sheets.googleapis.com/v4/spreadsheets/spreadsheet-id/values/Sheet1:append?valueInputOption=RAW",
            }
        `)

        const continuationResponse = await tester.invokeFetchResponse(fetchResponse.invocation, {
            status: 200,
            body: { status: 'OK' },
        })

        expect(continuationResponse.logs).toMatchInlineSnapshot(`
            [
              {
                "level": "debug",
                "message": "Function completed in [REPLACED]",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
            ]
        `)
        expect(continuationResponse.error).toMatchInlineSnapshot(`undefined`)
        expect(continuationResponse.finished).toEqual(true)
        expect(continuationResponse.invocation.queueParameters).toMatchInlineSnapshot(`undefined`)
    })

    it('should throw an error if the update fails', async () => {
        let response = await tester.invoke(defaultInputs, defaultGlobals)

        response = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { message: 'Bad Request' },
        })

        expect(response.error).toMatchInlineSnapshot(
            `"Error from sheets.googleapis.com (status 400): {'message': 'Bad Request'}"`
        )
        expect(response.logs.filter((l) => l.level === 'error').map((l) => l.message)).toMatchInlineSnapshot(`
            [
              "Error executing function on event event-id: Error('Error from sheets.googleapis.com (status 400): {\\'message\\': \\'Bad Request\\'}')",
            ]
        `)
        expect(response.finished).toEqual(true)
    })
})
