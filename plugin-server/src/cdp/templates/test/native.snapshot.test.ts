import { DateTime } from 'luxon'

import { SAMPLE_GLOBALS } from '~/cdp/_tests/fixtures'

import { NATIVE_HOG_FUNCTIONS } from '../index'
import { DestinationTester, generateTestData } from './native-test-helpers'

const template = NATIVE_HOG_FUNCTIONS[0]

const testDestination = new DestinationTester(template)

describe(`Testing snapshots for ${template.id} destination:`, () => {
    beforeEach(() => {
        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
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
            //   const request = responses[0].request
            //   const rawBody = await request.text()
            //
            //   try {
            //     const json = JSON.parse(rawBody)
            //     expect(json).toMatchSnapshot()
            //     return
            //   } catch (err) {
            //     expect(rawBody).toMatchSnapshot()
            //   }
            //
            //   expect(request.headers).toMatchSnapshot()
        })
    }
})
