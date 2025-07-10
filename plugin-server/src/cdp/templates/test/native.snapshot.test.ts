import { DateTime, Settings } from 'luxon'

import { SAMPLE_GLOBALS } from '~/cdp/_tests/fixtures'

import { NATIVE_HOG_FUNCTIONS } from '../index'
import { DestinationTester, generateTestData } from './test-helpers'

for (const template of NATIVE_HOG_FUNCTIONS) {
    const testDestination = new DestinationTester(template)

    describe(`Testing snapshots for ${template.id} destination:`, () => {
        beforeEach(() => {
            Settings.defaultZone = 'UTC'
            const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
            jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
        })

        afterEach(() => {
            Settings.defaultZone = 'system'
            jest.useRealTimers()
        })

        for (const mapping of template.mapping_templates) {
            it.each(['required fields', 'all fields'])(`${mapping.name} mapping - %s`, async (required) => {
                const seedName = `${template.id}#${mapping.name}`
                const inputs = generateTestData(seedName, template.inputs_schema, required === 'required fields')
                const mappingInputs = generateTestData(
                    seedName,
                    mapping.inputs_schema ?? [],
                    required === 'required fields'
                )

                const responses = await testDestination.invokeMapping(
                    mapping.name,
                    SAMPLE_GLOBALS,
                    { ...inputs, debug_mode: true },
                    mappingInputs
                )

                responses.logs.forEach((x) => {
                    if (typeof x.message === 'string' && x.message.includes('Function completed in')) {
                        x.message = 'Function completed in [REPLACED]'
                    }
                })
                responses.invocation.id = 'invocation-id'

                expect(responses).toMatchSnapshot()
            })
        }
    })
}
