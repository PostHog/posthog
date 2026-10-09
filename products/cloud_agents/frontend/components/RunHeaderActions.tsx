import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { cloudAgentRunLogic } from '../logics/cloudAgentRunLogic'

export function RunHeaderActions(): JSX.Element | null {
    const { run, isActive, cancelling } = useValues(cloudAgentRunLogic)
    const { cancelRun } = useActions(cloudAgentRunLogic)

    if (!run) {
        return null
    }
    return (
        <>
            {isActive && (
                <LemonButton
                    type="secondary"
                    status="danger"
                    size="small"
                    loading={cancelling}
                    disabledReason={cancelling ? 'Canceling the run' : undefined}
                    onClick={() =>
                        LemonDialog.open({
                            title: 'Cancel this run?',
                            description:
                                'The agent stops and the sandbox shuts down. You pay for the time used up to now. Work that the agent did not push is lost. A canceled run is done and cannot continue.',
                            primaryButton: {
                                children: 'Cancel run',
                                status: 'danger',
                                onClick: cancelRun,
                                'data-attr': 'cloud-agents-run-cancel-confirm',
                            },
                            secondaryButton: { children: 'Keep running' },
                        })
                    }
                    data-attr="cloud-agents-run-cancel"
                >
                    Cancel run
                </LemonButton>
            )}
            {run.result.pr_url && (
                <LemonButton
                    type="primary"
                    size="small"
                    to={run.result.pr_url}
                    targetBlank
                    sideIcon={<IconExternal />}
                    data-attr="cloud-agents-run-view-pr"
                >
                    View pull request
                </LemonButton>
            )}
        </>
    )
}
