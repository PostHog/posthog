import { SAMPLE_GLOBALS } from '~/cdp/_tests/fixtures'

import { NATIVE_HOG_FUNCTIONS_BY_ID } from '../../index'
import { DestinationTester, generateTestData } from '../../test/test-helpers'

const template = NATIVE_HOG_FUNCTIONS_BY_ID['native-webhook']

describe(`${template.name} template`, () => {
    const tester = new DestinationTester(template!)

    beforeEach(() => {
        tester.beforeEach()
    })

    afterEach(() => {
        tester.afterEach()
    })

    it('should handle a failing request', async () => {
        const inputs = generateTestData(template.id, template.inputs_schema)
        const mappingInputs = generateTestData(template.id, template.mapping_templates[0].inputs_schema ?? [])

        tester.mockFetchResponse({
            status: 400,
            body: { status: 'ERROR' },
            headers: { 'content-type': 'application/json' },
        })

        const response = await tester.invokeMapping(
            template.mapping_templates[0].name,
            SAMPLE_GLOBALS,
            { ...inputs, debug_mode: true },
            mappingInputs
        )

        expect(response.logs).toMatchInlineSnapshot(`
            [
              {
                "level": "debug",
                "message": "config, {"debug_mode":true,"apiKey":"0wayUUN$Z5","url":"http://jaj.mu/iroti","method":"POST","body":{"event":"test","person":"person-id"},"internal_associated_mapping":"send"}",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "endpoint, http://jaj.mu/iroti",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "options, {"method":"POST","headers":{"Content-Type":"application/json"},"json":{"event":"test","person":"person-id"}}",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "fetchOptions, {"method":"POST","headers":{"User-Agent":"PostHog.com/1.0","Content-Type":"application/json"},"body":"{\\"event\\":\\"test\\",\\"person\\":\\"person-id\\"}"}",
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
