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
    condition_companions: [],
    can_resolve_subject: true,
    setup_snippet: 'HOG_HOST: {host}',
} as WorkloadProviderApi

describe('workload condition presets', () => {
    it.each<[string, WorkloadConditionRow[], ReturnType<typeof conditionsFromRows>]>([
        [
            'a branch preset with its fixed event',
            [{ preset: 'branch_push', value: 'main' }],
            { conditions: { ref: 'refs/heads/main', event_name: 'push' } },
        ],
        [
            'a preset and a custom claim',
            [
                { preset: 'environment', value: 'production' },
                { preset: CUSTOM_CONDITION, claim: 'event_name', value: 'workflow_dispatch' },
            ],
            { conditions: { environment: 'production', event_name: 'workflow_dispatch' } },
        ],
        [
            // A half-filled branch preset must not save a policy that trusts every push.
            'a preset whose field is empty',
            [{ preset: 'branch_push', value: ' ' }],
            { conditions: {} },
        ],
        [
            'two rows that ask for different values of one claim',
            [
                { preset: 'branch_push', value: 'main' },
                { preset: CUSTOM_CONDITION, claim: 'event_name', value: 'schedule' },
            ],
            {
                conditions: { ref: 'refs/heads/main', event_name: 'push' },
                conflict: 'Two conditions ask for different values of Event.',
            },
        ],
    ])('turns %s into conditions', (_name, rows, result) => {
        expect(conditionsFromRows(rows, PROVIDER)).toEqual(result)
    })

    it.each<[string, Record<string, string>, WorkloadConditionRow[]]>([
        [
            'conditions that fit the presets as the preset rows',
            { ref: 'refs/heads/main', event_name: 'push', environment: 'production' },
            [
                { preset: 'branch_push', value: 'main' },
                { preset: 'environment', value: 'production' },
            ],
        ],
        [
            'conditions that fit no preset as custom rows',
            { ref: 'refs/tags/v1', event_name: 'push' },
            [
                { preset: CUSTOM_CONDITION, claim: 'ref', value: 'refs/tags/v1' },
                { preset: CUSTOM_CONDITION, claim: 'event_name', value: 'push' },
            ],
        ],
    ])('shows stored %s', (_name, conditions, rows) => {
        expect(rowsFromConditions(conditions, PROVIDER)).toEqual(rows)
    })
})
