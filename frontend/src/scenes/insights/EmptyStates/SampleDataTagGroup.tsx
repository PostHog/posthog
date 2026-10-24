import clsx from 'clsx'
import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { LemonButton, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { setupWizardStatusLogic } from 'scenes/onboarding/shared/setupWizardStatusLogic'

import { isSampleDataStatic } from './isSampleDataStatic'
import { SampleDataTag } from './SampleDataTag'

export function SampleDataTagGroup({ className, children }: { className?: string; children?: ReactNode }): JSX.Element {
    const { setupStatus } = useValues(setupWizardStatusLogic)

    return (
        <div className={clsx('flex items-center gap-1', className)}>
            {setupStatus?.kind === 'pull_request' && !setupStatus.pullRequest.merged && (
                <LemonButton size="xsmall" type="primary" to={setupStatus.pullRequest.url} targetBlank>
                    Merge setup PR
                </LemonButton>
            )}
            {setupStatus?.kind === 'installing' && (
                <Tooltip
                    title={
                        <div className="max-w-72 space-y-1.5 p-0.5">
                            <div className="font-semibold">Setup wizard is running</div>
                            {setupStatus.mode === 'cloud' ? (
                                <p className="m-0">
                                    The AI setup wizard is installing PostHog in the cloud, on a copy of your codebase.
                                    Once it's done, it will open a pull request for you to review and merge.
                                </p>
                            ) : (
                                <p className="m-0">
                                    The AI setup wizard is installing PostHog in your codebase from your terminal.
                                    You'll see real data here soon after it's done.
                                </p>
                            )}
                        </div>
                    }
                    placement="bottom"
                    delayMs={0}
                >
                    <LemonTag type="muted" className="gap-1 cursor-help">
                        <Spinner className="text-xs" frozen={isSampleDataStatic()} />
                        Installing PostHog...
                    </LemonTag>
                </Tooltip>
            )}
            {children}
            <SampleDataTag />
        </div>
    )
}
