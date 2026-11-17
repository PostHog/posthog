import { expectLogic, partial } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { replacedTaggerLogic } from './replacedTaggerLogic'

describe('replacedTaggerLogic', () => {
    let requestedEvaluationIds: (string | null)[]

    beforeEach(() => {
        requestedEvaluationIds = []
        useMocks({
            get: {
                '/api/projects/:team_id/taggers/': ({ request }) => {
                    requestedEvaluationIds.push(new URL(request.url).searchParams.get('migrated_to_evaluation_id'))
                    return [200, { results: [{ id: 'tagger-1', name: 'Support topic' }] }]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
    })

    it('finds the tagger once the taggers flag resolves after mount', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        const logic = replacedTaggerLogic({ evaluationId: 'eval-1' })
        logic.mount()
        expect(requestedEvaluationIds).toEqual([])

        await expectLogic(logic, () => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.LLM_ANALYTICS_TAGS], {
                [FEATURE_FLAGS.LLM_ANALYTICS_TAGS]: true,
            })
        })
            .toDispatchActions(['loadReplacedTaggerSuccess'])
            .toMatchValues({ replacedTagger: partial({ name: 'Support topic' }) })
        expect(requestedEvaluationIds).toEqual(['eval-1'])
    })
})
