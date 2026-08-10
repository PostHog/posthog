import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { ONBOARDING_TOOLS, ONBOARDING_USE_CASES, SUPPORTED_TOOL_PRODUCTS } from '../shared/useCases'
import { productEnablementStepLogic } from './productEnablementStepLogic'

describe('productEnablementStepLogic', () => {
    let logic: ReturnType<typeof productEnablementStepLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = productEnablementStepLogic()
        logic.mount()
    })

    it('registers one secondary intent per selected tool', async () => {
        const intents: any[] = []
        useMocks({
            patch: {
                '/api/environments/:team_id/add_product_intent/': async ({ request }) => {
                    intents.push(await request.json())
                    return [200, { product_intents: [] }]
                },
            },
        })
        await logic.asyncActions.enableTools([
            ProductKey.ERROR_TRACKING,
            ProductKey.WEB_ANALYTICS,
            ProductKey.EXPERIMENTS,
        ])

        expect(intents).toHaveLength(3)
        expect(intents.map((intent) => intent.product_type)).toEqual([
            ProductKey.ERROR_TRACKING,
            ProductKey.WEB_ANALYTICS,
            ProductKey.EXPERIMENTS,
        ])
        for (const intent of intents) {
            expect(intent.intent_context).toBe('onboarding product selected - secondary')
        }
        expect(logic.values.addingTools).toBe(false)
    })

    it('covers every supported tool with a use case', () => {
        const coveredProducts = new Set(
            ONBOARDING_USE_CASES.flatMap((useCase) => [
                ...useCase.tools.map((tool) => ONBOARDING_TOOLS[tool].productKey),
                ...(useCase.additionalTools ?? []),
            ])
        )

        expect(coveredProducts).toEqual(new Set(SUPPORTED_TOOL_PRODUCTS))
    })
})
