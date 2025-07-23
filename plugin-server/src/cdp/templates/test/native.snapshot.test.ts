import { SAMPLE_GLOBALS } from '~/cdp/_tests/fixtures'

import { NATIVE_HOG_FUNCTIONS } from '../index'
import { DestinationTester, generateTestData } from './test-helpers'

for (const template of NATIVE_HOG_FUNCTIONS) {
    const testDestination = new DestinationTester(template)

    describe(`Testing snapshots for ${template.id} destination:`, () => {
        beforeEach(() => {
            testDestination.beforeEach()
        })

        afterEach(() => {
            testDestination.afterEach()
        })

        it.each(['required fields', 'all fields'])(`%s`, async (required) => {
            const seedName = template.id
            const inputs = generateTestData(seedName, template.inputs_schema, required === 'required fields')

            const responses = await testDestination.invoke(SAMPLE_GLOBALS, { ...inputs, debug_mode: true })

            expect(responses).toMatchSnapshot()
        })
    })
}
