import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { FeatureFlagEvaluationContextMatchMode } from '~/types'

import { featureFlagEvaluationContextsLogic } from './featureFlagEvaluationContextsLogic'

describe('featureFlagEvaluationContextsLogic', () => {
    let logic: ReturnType<typeof featureFlagEvaluationContextsLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('initializes localMatchMode from props', async () => {
        logic = featureFlagEvaluationContextsLogic({
            flagId: 'new',
            context: 'form',
            tags: [],
            evaluationContexts: ['app', 'docs'],
            matchMode: FeatureFlagEvaluationContextMatchMode.ALL,
        })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            localMatchMode: FeatureFlagEvaluationContextMatchMode.ALL,
        })
    })

    it('defaults localMatchMode to ANY when prop is missing', async () => {
        logic = featureFlagEvaluationContextsLogic({
            flagId: 'new',
            context: 'form',
            tags: [],
            evaluationContexts: [],
            // matchMode intentionally omitted
        } as any)
        logic.mount()

        await expectLogic(logic).toMatchValues({
            localMatchMode: FeatureFlagEvaluationContextMatchMode.ANY,
        })
    })

    it('updates localMatchMode on setLocalMatchMode', async () => {
        logic = featureFlagEvaluationContextsLogic({
            flagId: 'new',
            context: 'form',
            tags: [],
            evaluationContexts: ['app', 'docs'],
            matchMode: FeatureFlagEvaluationContextMatchMode.ANY,
        })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setLocalMatchMode(FeatureFlagEvaluationContextMatchMode.ALL)
        }).toMatchValues({
            localMatchMode: FeatureFlagEvaluationContextMatchMode.ALL,
        })
    })

    it('resets localMatchMode to the prop value when cancelling edits', async () => {
        logic = featureFlagEvaluationContextsLogic({
            flagId: 'new',
            context: 'sidebar',
            tags: [],
            evaluationContexts: ['app', 'docs'],
            matchMode: FeatureFlagEvaluationContextMatchMode.ANY,
        })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setLocalMatchMode(FeatureFlagEvaluationContextMatchMode.ALL)
            logic.actions.cancelEditingContexts()
        }).toMatchValues({
            localMatchMode: FeatureFlagEvaluationContextMatchMode.ANY,
        })
    })
})
