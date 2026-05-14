import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { detectFlowsLogic } from './detectFlowsLogic'

export function DetectFlowsFormModal(): JSX.Element {
    const { formModalOpen, integrationId, repository, domain, submitting, canSubmit } = useValues(detectFlowsLogic)
    const { closeFormModal, setIntegrationId, setRepository, setDomain, submitDetectFlows } =
        useActions(detectFlowsLogic)
    const { integrations } = useValues(integrationsLogic)

    const handleRepositoryChange = (repoName: string): void => {
        if (!repoName) {
            setRepository('')
            return
        }
        const integration = integrations?.find((i) => i.id === integrationId)
        const owner = integration?.config?.account?.name || integration?.config?.account?.login
        setRepository(owner ? `${owner}/${repoName}` : repoName)
    }

    const pickerValue = repository?.split('/')?.pop() ?? ''

    return (
        <LemonModal
            isOpen={formModalOpen}
            onClose={closeFormModal}
            title="Auto-detect key flows"
            description="Analyze a GitHub repository and propose the most important user flows to test."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeFormModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitDetectFlows}
                        loading={submitting}
                        disabledReason={!canSubmit ? 'Select a repository and enter a domain' : undefined}
                    >
                        Detect flows
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <div>
                    <label className="block text-sm font-medium mb-2">GitHub integration</label>
                    <IntegrationChoice
                        integration="github"
                        value={integrationId ?? undefined}
                        onChange={(id) => {
                            setIntegrationId(id ?? null)
                            setRepository('')
                        }}
                        redirectUrl="/agentic_tests"
                    />
                </div>

                {integrationId ? (
                    <div>
                        <label className="block text-sm font-medium mb-2">Repository</label>
                        <GitHubRepositoryPicker
                            integrationId={integrationId}
                            value={pickerValue}
                            onChange={handleRepositoryChange}
                        />
                    </div>
                ) : null}

                <div>
                    <label className="block text-sm font-medium mb-2">Product domain</label>
                    <LemonInput value={domain} onChange={setDomain} placeholder="e.g. us.posthog.com" />
                    <p className="text-xs text-muted mt-1">
                        The domain where the product is deployed. The agent will figure out specific starting URLs per
                        flow.
                    </p>
                </div>
            </div>
        </LemonModal>
    )
}
