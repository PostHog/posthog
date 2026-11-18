import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import type { WorkloadProvidersResponseApi } from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { workloadTrustPoliciesLogic } from './workloadTrustPoliciesLogic'
import { WorkloadTrustPolicyModal } from './WorkloadTrustPolicyModal'

const providers: WorkloadProvidersResponseApi = {
    supported: [
        {
            key: 'github_actions',
            name: 'GitHub Actions',
            issuer: 'https://token.actions.githubusercontent.com',
            docs_url: 'https://posthog.com/docs/api/workload-identity/github-actions',
            subject_claim: { name: 'repository_id', label: 'Repository ID', help_text: '', placeholder: '' },
            subject_name_claim: { name: 'repository', label: 'Repository', help_text: '', placeholder: '' },
            condition_claims: [],
            required_condition_claims: [],
            account_condition_claims: [],
            condition_companions: [],
            condition_presets: [],
            required_presets: [],
            default_presets: [],
            can_resolve_subject: false,
            subject_lookup_conditions: {},
            setup_snippet: '',
        },
    ],
    job_settings: { host: 'https://us.posthog.com', project_id: 997, host_in_posthog_json: true },
    grantable_scopes: ['annotation:read', 'annotation:write', 'error_tracking:read', 'error_tracking:write'],
    risky_scopes: {},
}

describe('<WorkloadTrustPolicyModal />', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/workload_trust_policies/': { count: 0, next: null, results: [] },
                '/api/projects/:team_id/workload_trust_policies/providers/': providers,
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('keeps the chosen scopes when someone searches them', async () => {
        const logic = workloadTrustPoliciesLogic()
        logic.mount()
        logic.actions.loadProvidersSuccess(providers)
        logic.actions.setEditingPolicyId('new')
        render(
            <Provider>
                <WorkloadTrustPolicyModal />
            </Provider>
        )

        await userEvent.type(screen.getByPlaceholderText('Search scopes'), 'annot')
        await userEvent.click(screen.getByText('Read'))

        expect(logic.values.editingPolicy.scopes).toEqual(['annotation:read'])
        expect(screen.queryByText('Error tracking')).not.toBeInTheDocument()
    })
})
