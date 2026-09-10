import { randomUUID } from 'crypto'

import { DBHogFunctionTemplate } from '~/cdp/types'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { Hub } from '~/types'

import { insertHogFunctionTemplate } from '../../_tests/fixtures'
import { HogFunctionTemplateManagerService } from './hog-function-template-manager.service'

describe('HogFunctionTemplateManager', () => {
    let hub: Hub
    let manager: HogFunctionTemplateManagerService
    let hogFunctionsTemplates: DBHogFunctionTemplate[]
    let templateId: string

    beforeEach(async () => {
        hub = await createHub()
        manager = new HogFunctionTemplateManagerService(hub.postgres)

        hogFunctionsTemplates = []
        templateId = randomUUID()

        hogFunctionsTemplates.push(
            await insertHogFunctionTemplate(hub.postgres, {
                id: templateId,
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
        const items = await manager.getHogFunctionTemplate(templateId)

        expect(forSnapshot(items, { overrides: { template_id: '<TEMPLATE_ID>' } })).toMatchInlineSnapshot(`
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
              "template_id": "<TEMPLATE_ID>",
              "type": "destination",
            }
        `)
    })
})
