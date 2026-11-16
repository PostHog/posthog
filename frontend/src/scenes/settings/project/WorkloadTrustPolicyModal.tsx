import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'

import { ScopeAccessRow } from 'lib/components/ScopeAccessRow/ScopeAccessRow'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { riskyScopeWarning } from 'lib/scopes'

import { WorkloadConditionRows } from './WorkloadConditionRows'
import { WorkloadProviderIcon } from './WorkloadProviderIcon'
import { WorkloadSetupSnippet } from './WorkloadSetupSnippet'
import { WorkloadSubjectFields } from './WorkloadSubjectFields'
import { workloadTrustPoliciesLogic } from './workloadTrustPoliciesLogic'

export function WorkloadTrustPolicyModal(): JSX.Element {
    const {
        editingPolicyId,
        editingPolicyChanged,
        isEditingPolicySubmitting,
        providers,
        scopeRows,
        scopeLevels,
        scopeSearchTerm,
        editingProvider,
        showingSetup,
    } = useValues(workloadTrustPoliciesLogic)
    const { setEditingPolicyId, submitEditingPolicy, setScopeLevel, setScopeSearchTerm } =
        useActions(workloadTrustPoliciesLogic)

    const isNew = editingPolicyId === 'new'
    const close = (): void => setEditingPolicyId(null)

    if (showingSetup && editingProvider?.setup_snippet && providers) {
        return (
            <LemonModal
                title="Set up the workload"
                isOpen={!!editingPolicyId}
                onClose={close}
                width="40rem"
                footer={
                    <LemonButton type="primary" onClick={close} data-attr="workload-trust-policy-setup-done">
                        Done
                    </LemonButton>
                }
            >
                <WorkloadSetupSnippet provider={editingProvider} jobSettings={providers.job_settings} />
            </LemonModal>
        )
    }

    return (
        <Form logic={workloadTrustPoliciesLogic} formKey="editingPolicy">
            <LemonModal
                title={isNew ? 'Add trusted workload' : 'Edit trusted workload'}
                isOpen={!!editingPolicyId}
                onClose={close}
                width="40rem"
                hasUnsavedInput={editingPolicyChanged}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={close}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isEditingPolicySubmitting}
                            disabledReason={!editingPolicyChanged ? 'No changes to save' : undefined}
                            onClick={submitEditingPolicy}
                            data-attr="workload-trust-policy-save"
                        >
                            {isNew ? 'Add trusted workload' : 'Save'}
                        </LemonButton>
                    </>
                }
            >
                <div className="deprecated-space-y-4">
                    <LemonField name="issuer" label="Provider">
                        <LemonSegmentedButton
                            fullWidth
                            options={(providers?.supported ?? []).map((provider) => ({
                                value: provider.issuer,
                                label: provider.name,
                                icon: <WorkloadProviderIcon providerKey={provider.key} />,
                                'data-attr': `workload-trust-policy-provider-${provider.key}`,
                            }))}
                        />
                    </LemonField>
                    <WorkloadSubjectFields />
                    {editingProvider?.condition_claims.length ? (
                        <LemonField
                            name="conditions"
                            label="Which runs can get a token"
                            help="A token matches only when it meets every condition."
                        >
                            {() => <WorkloadConditionRows />}
                        </LemonField>
                    ) : null}
                    <LemonField name="name" label="Name">
                        <LemonInput placeholder="Production deploys" maxLength={200} />
                    </LemonField>
                    <LemonField
                        name="scopes"
                        label="Scopes"
                        help="Every token from this policy gets these scopes. Scopes that would let a token outlive itself aren't available."
                    >
                        <div className="w-full">
                            <LemonInput
                                type="search"
                                placeholder="Search scopes"
                                value={scopeSearchTerm}
                                onChange={setScopeSearchTerm}
                                className="mb-2"
                                size="small"
                            />
                            <div className="max-h-[40vh] overflow-y-auto deprecated-space-y-2">
                                {scopeRows.length === 0 ? (
                                    <div className="text-secondary text-sm py-2">No scopes match your search.</div>
                                ) : (
                                    scopeRows.map(({ key, label, disabledActions }) => (
                                        <ScopeAccessRow
                                            key={key}
                                            row={{
                                                key,
                                                label,
                                                value: scopeLevels[key] ?? 'none',
                                                warning: riskyScopeWarning(
                                                    key,
                                                    scopeLevels[key] ?? 'none',
                                                    providers?.risky_scopes ?? {}
                                                ),
                                                disabledReasons: {
                                                    read: disabledActions.includes('read')
                                                        ? 'Not available for workload tokens'
                                                        : undefined,
                                                    write: disabledActions.includes('write')
                                                        ? 'Not available for workload tokens'
                                                        : undefined,
                                                },
                                            }}
                                            onChange={setScopeLevel}
                                        />
                                    ))
                                )}
                            </div>
                        </div>
                    </LemonField>
                </div>
            </LemonModal>
        </Form>
    )
}
