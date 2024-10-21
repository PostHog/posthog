import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
    ReplayTabs,
    ReplayTemplateType,
    ReplayTemplateVariableType,
} from '~/types'

import type { sessionReplayTemplatesLogicType } from './sessionRecordingTemplatesLogicType'

export const replayTemplates: ReplayTemplateType[] = [
    {
        key: 'signup-flow',
        name: 'Signup flow',
        description: 'Watch how users sign up for your website. Look for any areas or steps that cause friction.',
        variables: [
            {
                type: 'pageview',
                name: 'Signup page URL',
                key: 'signup-page-url',
                value: '/signup',
                description: 'Complete or partial URL',
            },
        ],
        categories: ['B2B'],
    },
    {
        key: 'pricing-page',
        name: 'Pricing page',
        description: 'Watch how users navigate your pricing page. Look for any areas or steps that cause friction.',
        variables: [
            {
                type: 'pageview',
                name: 'Pricing page URL',
                key: 'pricing-page-url',
                description: 'Complete or partial URL',
            },
        ],
        categories: ['B2B'],
    },
    {
        key: 'upgrade-flow',
        name: 'Upgrade / subscribe flow',
        description:
            'Watch how users upgrade to the paid plan on your website. Look for any areas or steps that cause friction.',
        variables: [
            {
                type: 'pageview',
                name: 'Upgrade / subscribe page URL',
                key: 'upgrade-subscribe-page-url',
                description: 'Complete or partial URL',
            },
            {
                type: 'event',
                name: 'Upgrade / subscribe event',
                key: 'upgrade-subscribe-event',
                description: 'The event that triggers the upgrade / subscribe flow.',
            },
        ],
        categories: ['B2B'],
    },
    {
        key: 'onboarding-flow',
        name: 'Onboarding flow',
        description: 'Watch how users onboard to your website. Look for any areas or steps that cause friction.',
        variables: [
            {
                type: 'pageview',
                name: 'Onboarding page URL',
                key: 'onboarding-page-url',
                description: 'Complete or partial URL',
            },
        ],
        categories: ['B2B'],
    },
    {
        key: 'feature-usage',
        name: 'Feature usage',
        description:
            'Think of a feature you want to improve. Watch how users interact with it, and see where they get stuck.',
        variables: [
            {
                type: 'event',
                name: 'Feature event',
                key: 'feature-event',
                description: 'The event that indicates a user has interacted with the feature.',
            },
        ],
        categories: ['B2B', 'B2C'],
    },
    {
        key: 'purchase-flow',
        name: 'Purchase flow',
        description: 'Watch how users purchase from your website. Look for any areas or steps that cause friction.',
        variables: [
            {
                type: 'pageview',
                name: 'Purchase page URL',
                key: 'purchase-page-url',
                description: 'Complete or partial URL',
            },
        ],
        categories: ['B2C'],
    },
    {
        key: 'product-search',
        name: 'Product search',
        description:
            'Watch how users search for products on your website. Look for any areas or steps that cause friction.',
        variables: [
            {
                type: 'event',
                name: 'Product search event',
                key: 'product-search-event',
                description: 'The event that indicates a user has searched for something on your website.',
            },
        ],
        categories: ['B2C'],
    },
    {
        key: 'experiment',
        name: 'A/B test results',
        description: 'Watch how users interact with your A/B test. Look for any areas or steps that cause friction.',
        variables: [
            {
                type: 'flag',
                name: 'Feature flag',
                key: 'feature-flag',
                description: 'The feature flag that you want to observe.',
            },
        ],
        categories: ['More'],
    },
    {
        key: 'scattershot',
        name: 'Scattershot',
        description: 'Watch all recent replays, and see where users are getting stuck.',
        variables: [],
        categories: ['More'],
    },
    {
        key: 'person-property',
        name: 'Person property',
        description: 'Watch all replays for users with a specific property.',
        variables: [],
        categories: ['More'],
    },
]

// TODO IN THIS PR: What type should this be?
const getPageviewFilterValue = (pageview: string): Partial<any> => {
    return {
        key: 'visited_page',
        value: pageview,
        operator: PropertyOperator.IContains,
        type: PropertyFilterType.Recording,
    }
}

type ReplayTemplateLogicPropsType = {
    template: ReplayTemplateType
}

export const sessionReplayTemplatesLogic = kea<sessionReplayTemplatesLogicType>([
    path(() => ['scenes', 'session-recordings', 'templates', 'sessionReplayTemplatesLogic']),
    props({} as ReplayTemplateLogicPropsType),
    key((props) => props.template.key),
    actions({
        setVariables: (variables: ReplayTemplateVariableType[]) => ({ variables }),
        setVariable: (variable: ReplayTemplateVariableType) => ({ variable }),
        navigate: true,
        showVariables: true,
        hideVariables: true,
    }),
    reducers(({ props }) => ({
        variables: [
            props.template.variables as ReplayTemplateVariableType[],
            {
                setVariables: (_, { variables }) => variables,
                setVariable: (state, { variable }) =>
                    state.map((v) => (v.key === variable.key ? { ...variable, touched: true } : v)),
            },
        ],
        variablesVisible: [
            false,
            {
                showVariables: () => true,
                hideVariables: () => false,
            },
        ],
    })),
    selectors({
        filterGroup: [
            (s) => [s.variables],
            (variables) => {
                const filters = variables
                    .map((variable) => {
                        if (variable.type === 'pageview' && variable.value) {
                            return getPageviewFilterValue(variable.value)
                        }
                        if (variable.type === 'event' && variable.filterGroup) {
                            return variable.filterGroup
                        }
                        return undefined
                    })
                    .filter((filter) => filter !== undefined)

                const filterGroup: Partial<RecordingUniversalFilters> = {
                    filter_group: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: filters,
                            },
                        ],
                    },
                }
                return filterGroup
            },
        ],
        areAnyVariablesTouched: [(s) => [s.variables], (variables) => variables.some((v) => v.touched)],
    }),
    listeners(({ values }) => ({
        navigate: () => {
            router.actions.push(urls.replay(ReplayTabs.Home, values.filterGroup))
        },
    })),
    events(({ actions, props }) => ({
        afterMount: () => {
            actions.setVariables(props.template.variables)
        },
    })),
])
