import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { BuilderHog3 } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'

import { ProductKey } from '~/queries/schema/schema-general'

import { ciMonitoringDashboardSceneLogic } from '../scenes/ciMonitoringDashboardSceneLogic'

export function CIMonitoringSetupPrompt({ children }: { children: React.ReactNode }): JSX.Element {
    const { repo, repoLoading } = useValues(ciMonitoringDashboardSceneLogic)

    if (repoLoading && repo === null) {
        return (
            <div className="flex justify-center py-10">
                <Spinner />
            </div>
        )
    }

    if (repo === null) {
        return <ConnectRepoPrompt />
    }

    return <>{children}</>
}

function ConnectRepoPrompt(): JSX.Element {
    const { connectRepo } = useActions(ciMonitoringDashboardSceneLogic)
    const { repoLoading } = useValues(ciMonitoringDashboardSceneLogic)
    const [repoFullName, setRepoFullName] = useState('')

    const isValid = /^[^/]+\/[^/]+$/.test(repoFullName.trim())

    return (
        <ProductIntroduction
            productName="CI monitoring"
            productKey={ProductKey.CI_MONITORING}
            thingName="repository"
            titleOverride="Connect your GitHub repository"
            description="Track flaky tests, monitor CI health, and quarantine broken tests. Connect a GitHub repository to get started."
            isEmpty={true}
            customHog={BuilderHog3}
            actionElementOverride={
                <div className="flex flex-col gap-4">
                    <div className="flex items-center gap-2">
                        <LemonInput
                            placeholder="owner/repo (e.g. PostHog/posthog)"
                            value={repoFullName}
                            onChange={setRepoFullName}
                            onPressEnter={() => isValid && connectRepo(repoFullName.trim())}
                            className="min-w-80"
                        />
                        <LemonButton
                            type="primary"
                            onClick={() => connectRepo(repoFullName.trim())}
                            loading={repoLoading}
                            disabledReason={!isValid ? 'Enter a valid repo name (owner/repo)' : undefined}
                        >
                            Connect
                        </LemonButton>
                    </div>
                    <p className="text-sm text-secondary m-0">
                        After connecting, add a GitHub webhook pointing to{' '}
                        <code>{window.location.origin}/webhooks/github/ci</code> with the <strong>Workflow runs</strong>{' '}
                        event to start ingesting CI data.
                    </p>
                </div>
            }
        />
    )
}
