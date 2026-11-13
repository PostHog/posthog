import { createHash } from 'crypto'
import fs from 'fs'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './geoip.template'

// The Python port of this template (posthog/dags/geoip_enrichment.py) is tested against the same fixture.
// When this test fails after a template change, record a fixture for the new version, keep the old one
// (saved functions keep their source), and add the version to TEMPLATE_VERSIONS in the port.
const FIXTURE = path.resolve(__dirname, '../../../../../../posthog/dags/tests/fixtures/geoip_template_parity.json')

interface ParityCase {
    name: string
    properties: Record<string, unknown>
    expected: Record<string, unknown>
    node_error?: string
}

const fixture: { source_sha256: string; cases: ParityCase[] } = parseJSON(fs.readFileSync(FIXTURE, 'utf8'))

describe('geoip template parity fixture', () => {
    const tester = new TemplateTester(template)

    it('was recorded from the current template source', () => {
        // Saving a function trims the source, so the hash is of the trimmed text, as in geoip-noop.ts.
        const source = template.code.replace(/^[ \t\r\n]+|[ \t\r\n]+$/g, '')
        expect(createHash('sha256').update(source).digest('hex')).toEqual(fixture.source_sha256)
    })

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it.each(fixture.cases.map((testCase) => [testCase.name, testCase]))('%s', async (_name, testCase) => {
        const response = await tester.invoke({}, { event: { properties: testCase.properties } as any })

        if (testCase.node_error) {
            expect(String(response.error)).toContain(testCase.node_error)
            return
        }
        expect(response.error).toBeUndefined()
        const properties = (response.execResult as any)?.properties
        // The stored JSON text has to match too, including key order and number form.
        expect(JSON.stringify(properties)).toEqual(JSON.stringify(testCase.expected))
    })
})
