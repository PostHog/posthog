import type { WorkItemApi, WorkThreadApi } from 'products/today/frontend/generated/api.schemas'

const checkoutRelease: WorkItemApi = {
    type: 'release',
    id: '7',
    name: 'New checkout',
    kind_label: 'release',
    product: 'Releases',
    href: '/releases/7',
}

const checkoutFlag: WorkItemApi = {
    type: 'feature_flag',
    id: '128',
    name: 'checkout-v2',
    kind_label: 'flag',
    product: 'Feature flags',
    href: '/feature_flags/128',
}

const checkoutExperiment: WorkItemApi = {
    type: 'experiment',
    id: '42',
    name: 'One-page checkout',
    kind_label: 'experiment',
    product: 'Experiments',
    href: '/experiments/42',
}

const checkoutEarlyAccess: WorkItemApi = {
    type: 'early_access_feature',
    id: '19',
    name: 'New checkout',
    kind_label: 'early access feature',
    product: 'Early access',
    href: '/early_access_features/19',
}

export const checkoutWorkThread: WorkThreadApi = {
    key: 'release-7',
    name: 'New checkout',
    line: {
        key: 'main',
        steps: [
            {
                key: 'release-planned',
                title: 'Release planned: New checkout',
                description: 'A release groups everything that ships this change.',
                area: 'Release',
                item: checkoutRelease,
                facts: [
                    { label: 'Created', value: 'By you, 12 days ago' },
                    { label: 'Code', value: '2 merged pull requests mention checkout-v2' },
                ],
                chosen_label: 'Create a flag',
                started_from: null,
                options: [
                    {
                        key: 'create-flag',
                        kind: 'next',
                        label: 'Create a flag',
                        why: 'Nothing controls this change yet, so it cannot be rolled out gradually.',
                        gate: null,
                        helper: {
                            mode: 'in_place',
                            product: 'Feature flags',
                            does: 'Creates the flag and links it to this release.',
                            fields: [
                                { label: 'Key', value: 'checkout-v2' },
                                { label: 'Rollout', value: '0%' },
                                { label: 'Linked to', value: 'New checkout' },
                            ],
                            run_label: 'Create flag',
                            run: { type: 'action', to: null, action_id: 'create-flag', params: { key: 'checkout-v2' } },
                            mcp_tools: ['create-feature-flag'],
                        },
                    },
                ],
                alongside: [],
            },
            {
                key: 'flag-created',
                title: 'Flag created: checkout-v2',
                description: 'The flag decides who sees the new checkout.',
                area: 'Release',
                item: checkoutFlag,
                facts: [
                    { label: 'Rollout', value: '0% of users' },
                    { label: 'Code', value: 'Checked in 3 files' },
                ],
                chosen_label: 'Start an experiment',
                started_from: {
                    label: 'Create a flag',
                    why: 'Nothing controls this change yet, so it cannot be rolled out gradually.',
                },
                options: [
                    {
                        key: 'start-experiment',
                        kind: 'next',
                        label: 'Start an experiment',
                        why: 'Checkout conversion is the goal for this release. An experiment shows whether the change moves it.',
                        gate: null,
                        helper: {
                            mode: 'opens',
                            product: 'Experiments',
                            does: 'Opens a draft experiment on this flag, ready to launch.',
                            fields: [
                                { label: 'Flag', value: 'checkout-v2' },
                                { label: 'Primary metric', value: 'Checkout conversion' },
                                { label: 'Split', value: '50 / 50' },
                            ],
                            run_label: 'Open experiment',
                            run: {
                                type: 'link',
                                to: '/experiments/new?feature_flag=128',
                                action_id: null,
                                params: null,
                            },
                            mcp_tools: ['experiment-create'],
                        },
                    },
                    {
                        key: 'roll-out-10',
                        kind: 'next',
                        label: 'Roll out to 10%',
                        why: 'The quickest path if you do not need a comparison.',
                        gate: null,
                        helper: {
                            mode: 'in_place',
                            product: 'Feature flags',
                            does: 'Sets the flag to 10% of users.',
                            fields: [
                                { label: 'Flag', value: 'checkout-v2' },
                                { label: 'Rollout', value: '10%' },
                            ],
                            run_label: 'Roll out',
                            run: {
                                type: 'action',
                                to: null,
                                action_id: 'set-flag-rollout',
                                params: { flagId: 128, percentage: 10 },
                            },
                            mcp_tools: ['feature-flag-set-release-condition-rollout'],
                        },
                    },
                    {
                        key: 'early-access',
                        kind: 'alongside',
                        label: 'Add to early access',
                        why: '14 people asked for a faster checkout in feature requests.',
                        gate: null,
                        helper: {
                            mode: 'in_place',
                            product: 'Early access',
                            does: 'Lets people opt in to the new checkout before release.',
                            fields: [
                                { label: 'Flag', value: 'checkout-v2' },
                                { label: 'Stage', value: 'Beta' },
                            ],
                            run_label: 'Add to early access',
                            run: {
                                type: 'action',
                                to: null,
                                action_id: 'create-early-access-feature',
                                params: { flagId: 128 },
                            },
                            mcp_tools: ['early-access-feature-create'],
                        },
                    },
                ],
                alongside: [
                    {
                        key: 'early-access',
                        steps: [
                            {
                                key: 'early-access-open',
                                title: 'Early access open: New checkout',
                                description: 'People can opt in to the new checkout before release.',
                                area: 'Release',
                                item: checkoutEarlyAccess,
                                facts: [
                                    { label: 'Opted in', value: '6 so far' },
                                    { label: 'Asked for it', value: '14 feature requests' },
                                ],
                                chosen_label: null,
                                started_from: {
                                    label: 'Add to early access',
                                    why: '14 people asked for a faster checkout in feature requests.',
                                },
                                options: [
                                    {
                                        key: 'survey-beta-users',
                                        kind: 'next',
                                        label: 'Survey the beta users',
                                        why: 'Nobody has given feedback on the new flow yet.',
                                        gate: 'Opens when 20 people have opted in. 14 to go.',
                                        helper: {
                                            mode: 'in_place',
                                            product: 'Surveys',
                                            does: 'Creates a two-question survey for people in the beta.',
                                            fields: [
                                                { label: 'Shown to', value: 'People who opted in' },
                                                { label: 'Questions', value: 'Rating, then open text' },
                                            ],
                                            run_label: 'Create survey',
                                            run: {
                                                type: 'action',
                                                to: null,
                                                action_id: 'create-survey',
                                                params: { flagId: 128 },
                                            },
                                            mcp_tools: ['survey-create'],
                                        },
                                    },
                                ],
                                alongside: [],
                            },
                        ],
                    },
                ],
            },
            {
                key: 'experiment-result',
                title: 'Experiment has a result: One-page checkout',
                description: 'The experiment compares the new checkout with the current one.',
                area: 'Release',
                item: checkoutExperiment,
                facts: [
                    { label: 'Result', value: 'Variant converts 4.8%, control 4.1%' },
                    { label: 'Sample', value: '12,400 exposures over 9 days' },
                    { label: 'Confidence', value: 'Significant at 95%' },
                ],
                chosen_label: null,
                started_from: {
                    label: 'Start an experiment',
                    why: 'Checkout conversion is the goal for this release. An experiment shows whether the change moves it.',
                },
                options: [
                    {
                        key: 'ship-winner',
                        kind: 'next',
                        label: 'Ship the winner',
                        why: 'The result is significant and in your favor. More days will add little.',
                        gate: null,
                        helper: {
                            mode: 'in_place',
                            product: 'Feature flags',
                            does: 'Sets the flag to everyone and ends the experiment.',
                            fields: [
                                { label: 'Flag', value: 'checkout-v2' },
                                { label: 'Rollout', value: '100%' },
                                { label: 'Variant', value: 'One-page' },
                            ],
                            run_label: 'Ship variant',
                            run: {
                                type: 'action',
                                to: null,
                                action_id: 'ship-variant',
                                params: { experimentId: 42, variant: 'test' },
                            },
                            mcp_tools: ['experiment-ship-variant', 'feature-flag-roll-out-to-everyone'],
                        },
                    },
                    {
                        key: 'extend-week',
                        kind: 'next',
                        label: 'Extend by a week',
                        why: 'Weekend traffic is only 1 of the 9 days.',
                        gate: null,
                        helper: {
                            mode: 'opens',
                            product: 'Experiments',
                            does: 'Opens the experiment with its end date moved 7 days later.',
                            fields: [
                                { label: 'Experiment', value: 'One-page checkout' },
                                { label: 'New end date', value: 'In 7 days' },
                            ],
                            run_label: 'Open experiment',
                            run: { type: 'link', to: '/experiments/42', action_id: null, params: null },
                            mcp_tools: [],
                        },
                    },
                    {
                        key: 'watch-recordings',
                        kind: 'alongside',
                        label: 'Watch variant recordings',
                        why: '3 sessions in the variant show repeated clicks on the payment step.',
                        gate: null,
                        helper: {
                            mode: 'opens',
                            product: 'Session replay',
                            does: 'Opens a playlist of the variant sessions with repeated clicks.',
                            fields: [
                                { label: 'Filter', value: 'Variant One-page, repeated clicks' },
                                { label: 'Sorted by', value: 'Most activity first' },
                            ],
                            run_label: 'Open recordings',
                            run: { type: 'link', to: '/replay/home', action_id: null, params: null },
                            mcp_tools: ['session-recording-playlist-create'],
                        },
                    },
                ],
                alongside: [],
            },
        ],
    },
}

const autofillFlag: WorkItemApi = {
    type: 'feature_flag',
    id: '311',
    name: 'address-autofill',
    kind_label: 'flag',
    product: 'Feature flags',
    href: '/feature_flags/311',
}

export const finishedWorkThread: WorkThreadApi = {
    key: 'release-12',
    name: 'Address autofill',
    line: {
        key: 'main',
        steps: [
            {
                key: 'rolled-out',
                title: 'Rolled out to everyone',
                description: 'Address autofill is live for all users.',
                area: 'Release',
                item: autofillFlag,
                facts: [
                    { label: 'Rollout', value: '100% for 34 days' },
                    { label: 'Errors', value: 'Rate steady at 0.2%' },
                ],
                chosen_label: 'Clean up the flag',
                started_from: null,
                options: [
                    {
                        key: 'clean-up-flag',
                        kind: 'next',
                        label: 'Clean up the flag',
                        why: 'A flag at 100% is dead code once the release has settled.',
                        gate: null,
                        helper: {
                            mode: 'in_place',
                            product: 'Feature flags',
                            does: 'Archives the flag.',
                            fields: [{ label: 'Flag', value: 'address-autofill' }],
                            run_label: 'Archive flag',
                            run: { type: 'action', to: null, action_id: 'archive-flag', params: { flagId: 311 } },
                            mcp_tools: ['feature-flag-archive'],
                        },
                    },
                ],
                alongside: [],
            },
            {
                key: 'flag-cleaned-up',
                title: 'Flag cleaned up',
                description: 'The flag is archived and its checks are removed from the code.',
                area: 'Release',
                item: autofillFlag,
                facts: [
                    { label: 'Flag', value: 'Archived' },
                    { label: 'Code', value: 'Removed from 2 files' },
                ],
                chosen_label: null,
                started_from: {
                    label: 'Clean up the flag',
                    why: 'A flag at 100% is dead code once the release has settled.',
                },
                options: [
                    {
                        key: 'survey-users',
                        kind: 'alongside',
                        label: 'Survey users',
                        why: 'You have numbers but no words from users about address autofill.',
                        gate: null,
                        helper: {
                            mode: 'in_place',
                            product: 'Surveys',
                            does: 'Creates a one-question survey for people who used address autofill.',
                            fields: [
                                { label: 'Shown to', value: 'Users who saw address autofill' },
                                { label: 'Question', value: 'How was entering your address?' },
                            ],
                            run_label: 'Create survey',
                            run: { type: 'action', to: null, action_id: 'create-survey', params: { flagId: 311 } },
                            mcp_tools: [],
                        },
                    },
                ],
                alongside: [],
            },
        ],
    },
}
