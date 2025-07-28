import { SAMPLE_GLOBALS } from '~/cdp/_tests/fixtures'

import { NATIVE_HOG_FUNCTIONS_BY_ID } from '../../index'
import { DestinationTester, generateTestData } from '../../test/test-helpers'

const template = NATIVE_HOG_FUNCTIONS_BY_ID['native-google-sheets']

describe(`${template.name} template`, () => {
    const tester = new DestinationTester(template!)

    beforeEach(() => {
        tester.beforeEach()
    })

    afterEach(() => {
        tester.afterEach()
    })

    it('should work with default mapping', async () => {
        const mockRequest = jest.fn().mockResolvedValue({
            status: 200,
            json: () => Promise.resolve({ message: 'Success' }),
            text: () => Promise.resolve(JSON.stringify({ message: 'Success' })),
            headers: {},
        })

        const payload = {
            oauth: {
                access_token: '1234567890',
            },
            spreadsheet_id: 'spreadsheet-id',
            spreadsheet_name: 'Sheet1',
            fields: {
                event_name: '{event.event}',
                timestamp: '{event.timestamp}',
            },
            data_format: 'RAW',
        }

        await template.perform(mockRequest, { payload })

        expect(mockRequest).toHaveBeenCalledTimes(1)
        expect(mockRequest).toHaveBeenCalledWith(
            'https://sheets.googleapis.com/v4/spreadsheets/spreadsheet-id/values/Sheet1:append?valueInputOption=RAW',
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Authorization: 'Bearer 1234567890' },
                json: {
                    values: [['{event.event}', '{event.timestamp}']],
                },
            }
        )
    })

    it('should handle a failing request', async () => {
        const inputs = generateTestData(template.id, template.inputs_schema)

        tester.mockFetchResponse({
            status: 400,
            body: { status: 'ERROR' },
            headers: { 'content-type': 'application/json' },
        })

        const response = await tester.invoke(SAMPLE_GLOBALS, { ...inputs, debug_mode: true })

        expect(response.logs).toMatchInlineSnapshot(`
            [
              {
                "level": "debug",
                "message": "config, {"spreadsheet_name":"Sheet1","data_format":"RAW","fields":{"timestamp":"","event_name":"test"},"debug_mode":true,"oauth":"5#$gnF#z","spreadsheet_id":"5#$gnF#z"}",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "endpoint, https://sheets.googleapis.com/v4/spreadsheets/5#$gnF#z/values/Sheet1:append?valueInputOption=RAW",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "options, {"method":"POST","headers":{"Content-Type":"application/json","Authorization":"Bearer undefined"},"json":{"values":[["","test"]]}}",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "fetchOptions, {"method":"POST","headers":{"User-Agent":"PostHog.com/1.0","Content-Type":"application/json","Authorization":"Bearer undefined"},"body":"{\\"values\\":[[\\"\\",\\"test\\"]]}"}",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "warn",
                "message": "HTTP request failed with status 400 ({"status":"ERROR"}). ",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "error",
                "message": "Function failed: Error executing function on event uuid: Request failed with status 400 ({"status":"ERROR"})",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
            ]
        `)
    })
})
