import { DBHogFunctionTemplate } from '~/cdp/types'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { resetTestDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { insertHogFunctionTemplate } from '../../_tests/fixtures'
import { HogFunctionTemplateManagerService } from './hog-function-template-manager.service'

describe('HogFunctionTemplateManager', () => {
    let hub: Hub
    let manager: HogFunctionTemplateManagerService
    let hogFunctionsTemplates: DBHogFunctionTemplate[]

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        manager = new HogFunctionTemplateManagerService(hub)

        hogFunctionsTemplates = []

        hogFunctionsTemplates.push(
            await insertHogFunctionTemplate(hub.postgres, {
                id: 'template-testing-1',
                name: 'Test Hog Function team 1',
                inputs_schema: [
                    {
                        key: 'url',
                        type: 'string',
                        required: true,
                    },
                ],
                code: 'fetch(inputs.url)',
            })
        )
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('returns the hog functions templates', async () => {
        const items = await manager.getHogFunctionTemplate('template-testing-1')

        expect(forSnapshot(items)).toMatchInlineSnapshot(`
            {
              "bytecode": [
                "_H",
                1,
                32,
                "url",
                32,
                "inputs",
                1,
                2,
                2,
                "fetch",
                1,
                35,
              ],
              "free": true,
              "id": "<REPLACED-UUID-0>",
              "inputs_schema": [
                {
                  "key": "url",
                  "required": true,
                  "type": "string",
                },
              ],
              "name": "Test Hog Function team 1",
              "sha": "sha",
              "template_id": "template-testing-1",
              "type": "destination",
            }
        `)
    })
})
