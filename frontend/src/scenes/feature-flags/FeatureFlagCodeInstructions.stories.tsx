import { Meta } from '@storybook/react'

import { CodeInstructions, CodeInstructionsProps } from './FeatureFlagInstructions'
import { OPTIONS } from './FeatureFlagCodeOptions'
import { FeatureFlagType } from '~/types'
import { useStorybookMocks } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'

const REGULAR_FEATURE_FLAG: FeatureFlagType = {
    id: 1,
    name: 'test',
    key: 'test',
    rollout_percentage: 50,
    filters: {
        groups: [{ properties: [], rollout_percentage: null, variant: null }],
        multivariate: null,
        payloads: { true: '' },
    },
    features: [],
    active: true,
    deleted: false,
    created_at: '2021-05-05T12:00:00Z',
    created_by: null,
    experiment_set: [],
    is_simple_flag: false,
    ensure_experience_continuity: false,
    rollback_conditions: [],
    performed_rollback: false,
    can_edit: true,
    tags: [],
}

const GROUP_FEATURE_FLAG: FeatureFlagType = {
    ...REGULAR_FEATURE_FLAG,
    key: 'group-flag',
    filters: {
        aggregation_group_type_index: 1,
        groups: [{ properties: [], rollout_percentage: null, variant: null }],
        multivariate: null,
        payloads: { true: '' },
    },
}

const MULTIVARIATE_FEATURE_FLAG: FeatureFlagType = {
    ...REGULAR_FEATURE_FLAG,
    key: 'multivariate-flag',
    filters: {
        groups: [{ properties: [], rollout_percentage: null, variant: null }],
        payloads: {},
        multivariate: {
            variants: [
                { key: 'alpha', name: '', rollout_percentage: 50 },
                { key: 'beta', name: '', rollout_percentage: 50 },
            ],
        },
    },
}

const MULTIVARIATE_GROUP_WITH_PAYLOADS_FEATURE_FLAG: FeatureFlagType = {
    ...REGULAR_FEATURE_FLAG,
    key: 'multivariate-group-flag',
    filters: {
        aggregation_group_type_index: 1,
        groups: [{ properties: [], rollout_percentage: null, variant: null }],
        payloads: { alpha: 'abcd', beta: 'xyz' },
        multivariate: {
            variants: [
                { key: 'alpha', name: '', rollout_percentage: 50 },
                { key: 'beta', name: '', rollout_percentage: 50 },
            ],
        },
    },
}

const meta: Meta<typeof CodeInstructions> = {
    title: 'Scenes-App/Feature Flags/Code Examples',
    component: CodeInstructions,
    args: {
        options: OPTIONS,
        selectedLanguage: 'JavaScript',
        featureFlag: REGULAR_FEATURE_FLAG,
        showLocalEval: false,
        showBootstrap: false,
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
}
export default meta

export const CodeInstructionsOverview = (props: CodeInstructionsProps): JSX.Element => {
    useAvailableFeatures([AvailableFeature.GROUP_ANALYTICS, AvailableFeature.MULTIVARIATE_FLAGS])

    return <CodeInstructions {...props} />
}

export const CodeInstructionsReactNativeWithBootstrap = (): JSX.Element => {
    return <CodeInstructions selectedLanguage="React Native" options={OPTIONS} showBootstrap={true} />
}

export const CodeInstructionsPythonWithLocalEvaluation = (): JSX.Element => {
    return <CodeInstructions selectedLanguage="Python" options={OPTIONS} showLocalEval={true} />
}

export const CodeInstructionsRubyWithGroupFlagLocalEvaluation = (): JSX.Element => {
    useAvailableFeatures([AvailableFeature.GROUP_ANALYTICS, AvailableFeature.MULTIVARIATE_FLAGS])
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/groups_types/': [
                { group_type: 'project', group_type_index: 0, name_singular: null, name_plural: null },
                { group_type: 'organization', group_type_index: 1, name_singular: null, name_plural: null },
                { group_type: 'instance', group_type_index: 2, name_singular: null, name_plural: null },
            ],
        },
    })
    return (
        <CodeInstructions
            selectedLanguage="Ruby"
            options={OPTIONS}
            showLocalEval={true}
            featureFlag={GROUP_FEATURE_FLAG}
        />
    )
}

export const CodeInstructionsiOSWithMultivariateFlag = (): JSX.Element => {
    return <CodeInstructions selectedLanguage="iOS" options={OPTIONS} featureFlag={MULTIVARIATE_FEATURE_FLAG} />
}

export const CodeInstructionsNodeWithGroupMultivariateFlagLocalEvaluation = (): JSX.Element => {
    useAvailableFeatures([AvailableFeature.GROUP_ANALYTICS, AvailableFeature.MULTIVARIATE_FLAGS])
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/groups_types/': [
                { group_type: 'project', group_type_index: 0, name_singular: null, name_plural: null },
                { group_type: 'organization', group_type_index: 1, name_singular: null, name_plural: null },
                { group_type: 'instance', group_type_index: 2, name_singular: null, name_plural: null },
            ],
        },
    })
    return (
        <CodeInstructions
            selectedLanguage="Node.js"
            options={OPTIONS}
            showLocalEval={true}
            featureFlag={MULTIVARIATE_GROUP_WITH_PAYLOADS_FEATURE_FLAG}
        />
    )
}
