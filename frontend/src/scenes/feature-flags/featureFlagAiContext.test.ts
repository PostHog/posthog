import {
    AccessControlLevel,
    FeatureFlagBucketingIdentifier,
    FeatureFlagEvaluationRuntime,
    FeatureFlagGroupType,
    FeatureFlagType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { wrapWithPosthogContext } from 'products/posthog_ai/frontend/utils/posthogContextBlock'

import { featureFlagContextItems } from './featureFlagAiContext'

// The backend's own cap on a text attachment (MAX_TEXT_LENGTH in the posthog_ai backend). Asserting
// the literal rather than importing the frontend constant is deliberate: raising the frontend cap
// past what the backend accepts is exactly the regression these cases guard against.
const MAX_BACKEND_TEXT_LENGTH = 4096

describe('featureFlagContextItems', () => {
    const baseFeatureFlag: FeatureFlagType = {
        id: 1,
        key: 'test-flag',
        name: '',
        created_at: '2021-01-01',
        updated_at: '2021-01-01',
        created_by: null,
        is_remote_configuration: false,
        filters: { groups: [], payloads: {}, multivariate: null },
        deleted: false,
        archived: false,
        active: true,
        experiment_set: null,
        experiment_set_metadata: null,
        features: null,
        surveys: null,
        can_edit: true,
        tags: [],
        ensure_experience_continuity: null,
        user_access_level: AccessControlLevel.Admin,
        status: 'ACTIVE',
        has_encrypted_payloads: false,
        version: 0,
        last_modified_by: null,
        evaluation_runtime: FeatureFlagEvaluationRuntime.ALL,
        evaluation_contexts: [],
        bucketing_identifier: FeatureFlagBucketingIdentifier.DISTINCT_ID,
    }

    const personCondition: FeatureFlagGroupType = {
        properties: [
            { key: 'email', value: 'is_set', operator: PropertyOperator.IsSet, type: PropertyFilterType.Person },
        ],
        rollout_percentage: 50,
        variant: null,
    }

    function withFilters(filters: Partial<FeatureFlagType['filters']>): FeatureFlagType {
        return { ...baseFeatureFlag, filters: { ...baseFeatureFlag.filters, ...filters } }
    }

    function targetingValue(featureFlag: FeatureFlagType): string {
        const item = featureFlagContextItems(featureFlag).find((item) => item.type === 'feature_flag_targeting')
        if (!item?.value) {
            throw new Error('no targeting item')
        }
        return item.value
    }

    it('renders the release conditions into the context block the agent reads', () => {
        const block = wrapWithPosthogContext(
            'who matches this flag?',
            featureFlagContextItems(withFilters({ groups: [personCondition] }))
        )

        expect(block).toContain('feature_flag test-flag')
        expect(block).toContain('release_conditions')
        expect(block).toContain('email')
    })

    it('carries the targeting a group-targeted multivariate flag needs beyond its release conditions', () => {
        const targeting = JSON.parse(
            targetingValue(
                withFilters({
                    groups: [personCondition],
                    aggregation_group_type_index: 0,
                    multivariate: { variants: [{ key: 'control', rollout_percentage: 50 }] },
                    holdout_groups: [personCondition],
                })
            )
        )

        expect(targeting.aggregation_group_type_index).toBe(0)
        expect(targeting.multivariate.variants[0].key).toBe('control')
        expect(targeting.holdout_groups).toHaveLength(1)
    })

    const flagWithPastedValues = withFilters({
        groups: [
            {
                properties: [
                    {
                        key: 'email',
                        value: Array.from({ length: 500 }, (_, index) => `person${index}@example.com`),
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Person,
                    },
                ],
                rollout_percentage: 100,
                variant: null,
            },
        ],
    })

    const oversized: [string, FeatureFlagType][] = [
        ['a condition holding hundreds of pasted values', flagWithPastedValues],
        ['a very long description', { ...withFilters({ groups: [personCondition] }), name: 'x'.repeat(20000) }],
    ]

    test.each(oversized)('keeps the attachment under the backend limit with %s', (_name, featureFlag) => {
        const value = targetingValue(featureFlag)

        expect(value.length).toBeLessThanOrEqual(MAX_BACKEND_TEXT_LENGTH)
        expect(() => JSON.parse(value)).not.toThrow()
    })

    it('summarizes the release conditions it drops to fit', () => {
        const value = targetingValue(flagWithPastedValues)

        expect(value).not.toContain('person1@example.com')
        // Without the count the agent can't tell a flag with no targeting from one whose targeting
        // was too large to send.
        expect(JSON.parse(value).release_condition_count).toBe(1)
    })
})
