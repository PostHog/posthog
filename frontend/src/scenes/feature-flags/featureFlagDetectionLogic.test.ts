import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import { expectLogic, partial } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { cohortsModel } from '~/models/cohortsModel'
import { initKeaTests } from '~/test/init'
import { FeatureFlagEvaluationRuntime, PropertyFilterType, PropertyOperator } from '~/types'

import { featureFlagDetectionLogic } from './featureFlagDetectionLogic'
import { NEW_FLAG, featureFlagLogic } from './featureFlagLogic'

const MOCK_FLAG_CLEAN = {
    ...NEW_FLAG,
    id: 1,
    key: 'clean-flag',
}

const MOCK_FLAG_WITH_PERSON_PROP = {
    ...NEW_FLAG,
    id: 2,
    key: 'person-prop-flag',
    filters: {
        groups: [
            {
                properties: [
                    { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.Exact, value: 'test' },
                ],
                rollout_percentage: 100,
                variant: null,
            },
        ],
        multivariate: null,
        payloads: {},
    },
}

const MOCK_FLAG_WITH_IS_NOT_SET = {
    ...NEW_FLAG,
    id: 3,
    key: 'is-not-set-flag',
    evaluation_runtime: FeatureFlagEvaluationRuntime.SERVER,
    filters: {
        groups: [
            {
                properties: [
                    { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.IsNotSet, value: '' },
                ],
                rollout_percentage: 100,
                variant: null,
            },
        ],
        multivariate: null,
        payloads: {},
    },
}

describe('featureFlagDetectionLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('returns no findings for a clean flag', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/1/`]: () => [200, MOCK_FLAG_CLEAN],
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/1/status`]: () => [200, { status: 'active' }],
            },
        })

        const flagLogic = featureFlagLogic({ id: 1 })
        flagLogic.mount()
        await expectLogic(flagLogic).toFinishAllListeners()

        const logic = featureFlagDetectionLogic({ id: 1 })
        logic.mount()

        expectLogic(logic).toMatchValues({
            findings: [],
        })

        logic.unmount()
        flagLogic.unmount()
    })

    it('detects non-instant person properties', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/2/`]: () => [200, MOCK_FLAG_WITH_PERSON_PROP],
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/2/status`]: () => [200, { status: 'active' }],
            },
        })

        const flagLogic = featureFlagLogic({ id: 2 })
        flagLogic.mount()
        await expectLogic(flagLogic).toFinishAllListeners()

        const logic = featureFlagDetectionLogic({ id: 2 })
        logic.mount()

        expectLogic(logic).toMatchValues({
            findings: [
                partial({
                    id: 'non-instant-properties',
                    severity: 'info',
                }),
            ],
        })

        logic.unmount()
        flagLogic.unmount()
    })

    it('detects is_not_set operator', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/3/`]: () => [200, MOCK_FLAG_WITH_IS_NOT_SET],
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/3/status`]: () => [200, { status: 'active' }],
            },
        })

        const flagLogic = featureFlagLogic({ id: 3 })
        flagLogic.mount()
        await expectLogic(flagLogic).toFinishAllListeners()

        const logic = featureFlagDetectionLogic({ id: 3 })
        logic.mount()

        const findingIds = logic.values.findings.map((f) => f.id)
        expect(findingIds).toContain('is-not-set-operator')

        logic.unmount()
        flagLogic.unmount()
    })

    it('includes entity context in findings', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/2/`]: () => [200, MOCK_FLAG_WITH_PERSON_PROP],
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/2/status`]: () => [200, { status: 'active' }],
            },
        })

        const flagLogic = featureFlagLogic({ id: 2 })
        flagLogic.mount()
        await expectLogic(flagLogic).toFinishAllListeners()

        const logic = featureFlagDetectionLogic({ id: 2 })
        logic.mount()

        const finding = logic.values.findings[0]
        expect(finding.entityType).toBe('feature_flag')
        expect(finding.entityId).toBe(2)

        logic.unmount()
        flagLogic.unmount()
    })

    it('detects static cohort when cohortsModel has data', async () => {
        const staticCohort = {
            id: 10,
            name: 'Static Cohort',
            is_static: true,
            filters: { properties: { type: 'AND', values: [] } },
        }

        const cohortFlagData = {
            ...NEW_FLAG,
            id: 4,
            key: 'cohort-flag',
            evaluation_runtime: FeatureFlagEvaluationRuntime.SERVER,
            filters: {
                groups: [
                    {
                        properties: [
                            {
                                key: 'id',
                                type: PropertyFilterType.Cohort,
                                value: 10,
                                operator: PropertyOperator.In,
                            },
                        ],
                        rollout_percentage: 100,
                        variant: null,
                    },
                ],
                multivariate: null,
                payloads: {},
            },
        }

        useMocks({
            get: {
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/4/`]: () => [200, cohortFlagData],
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/4/status`]: () => [200, { status: 'active' }],
                '/api/projects/:team_id/cohorts/': () => [200, { count: 1, results: [staticCohort] }],
            },
        })

        const flagLogic = featureFlagLogic({ id: 4 })
        flagLogic.mount()

        const logic = featureFlagDetectionLogic({ id: 4 })
        logic.mount()

        await expectLogic(flagLogic).toFinishAllListeners()
        await expectLogic(cohortsModel).toFinishAllListeners()

        const findingIds = logic.values.findings.map((f) => f.id)
        expect(findingIds).toContain('static-cohort')

        logic.unmount()
        flagLogic.unmount()
    })
})
