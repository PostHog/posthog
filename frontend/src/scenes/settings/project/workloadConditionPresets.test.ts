import type { WorkloadProviderApi } from '~/generated/core/api.schemas'

import {
    CUSTOM_CONDITION,
    conditionsFromRows,
    rowsFromConditions,
    type WorkloadConditionRow,
} from './workloadConditionPresets'

const claim = (name: string, label: string): WorkloadProviderApi['condition_claims'][number] => ({
    name,
    label,
    help_text: '',
    placeholder: '',
})

const PROVIDER = {
    key: 'github_actions',
    name: 'GitHub Actions',
    issuer: 'https://token.actions.githubusercontent.com',
    docs_url: 'https://posthog.com/docs',
    subject_claim: claim('repository_id', 'Repository ID'),
    subject_name_claim: claim('repository', 'Repository'),
    condition_claims: [
        claim('ref', 'Branch or tag'),
        claim('event_name', 'Event'),
        claim('environment', 'Environment'),
    ],
    condition_presets: [
        {
            key: 'branch_push',
            label: 'Pushes to a branch',
            help_text: '',
            conditions: { ref: 'refs/heads/{value}', event_name: 'push' },
            takes_value: true,
            placeholder: 'main',
            default_value: 'main',
        },
        {
            key: 'environment',
            label: 'A deployment environment',
            help_text: '',
            conditions: { environment: '{value}' },
            takes_value: true,
            placeholder: 'production',
            default_value: 'production',
        },
    ],
    can_resolve_subject: true,
    setup_snippet: 'HOG_HOST: {host}\nHOG_PROJECT_ID: "{project_id}"',
} as WorkloadProviderApi

describe('workload condition presets', () => {
    it.each<[string, WorkloadConditionRow[], Record<string, string>]>([
        [
            'a branch preset with its fixed event',
            [{ preset: 'branch_push', value: 'main' }],
            { ref: 'refs/heads/main', event_name: 'push' },
        ],
        [
            'a preset and a custom claim',
            [
                { preset: 'environment', value: 'production' },
                { preset: CUSTOM_CONDITION, claim: 'event_name', value: 'workflow_dispatch' },
            ],
            { environment: 'production', event_name: 'workflow_dispatch' },
        ],
        [
            // A half-filled branch preset must not save a policy that trusts every push.
            'a preset whose field is empty',
            [{ preset: 'branch_push', value: ' ' }],
            {},
        ],
    ])('turns %s into conditions', (_name, rows, conditions) => {
        expect(conditionsFromRows(rows, PROVIDER)).toEqual({ conditions })
    })

    it('shows stored conditions as the rows that made them', () => {
        const conditions = { ref: 'refs/heads/main', event_name: 'push', environment: 'production' }

        expect(rowsFromConditions(conditions, PROVIDER)).toEqual([
            { preset: 'branch_push', value: 'main' },
            { preset: 'environment', value: 'production' },
        ])
    })

    it('shows a stored condition that fits no preset as a custom row', () => {
        expect(rowsFromConditions({ ref: 'refs/tags/v1', event_name: 'push' }, PROVIDER)).toEqual([
            { preset: CUSTOM_CONDITION, claim: 'ref', value: 'refs/tags/v1' },
            { preset: CUSTOM_CONDITION, claim: 'event_name', value: 'push' },
        ])
    })

    it('refuses two rows that ask for different values of one claim', () => {
        const rows = [
            { preset: 'branch_push', value: 'main' },
            { preset: CUSTOM_CONDITION, claim: 'event_name', value: 'schedule' },
        ]

        expect(conditionsFromRows(rows, PROVIDER).conflict).toBe('Two conditions ask for different values of Event.')
    })
})
