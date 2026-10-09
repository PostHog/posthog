import { useActions, useValues } from 'kea'

import { IconPlus, IconTerminal, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { claudeSubscriptionLogic } from '../logics/claudeSubscriptionLogic'
import { ClaudeSubscriptionConnectModal } from './ClaudeSubscriptionConnectModal'
import { LoadErrorBanner } from './LoadErrorBanner'

/** The Claude subscription of the signed-in user: its connected state, and the controls to connect or disconnect it. */
export function ClaudeSubscriptionConnection(): JSX.Element {
    const { claudeSubscription, claudeSubscriptionLoading, claudeSubscriptionLoadFailed, connected, connecting } =
        useValues(claudeSubscriptionLogic)
    const { loadClaudeSubscription, openConnectModal, disconnectClaudeSubscription } =
        useActions(claudeSubscriptionLogic)

    if (claudeSubscription === null) {
        return claudeSubscriptionLoadFailed ? (
            <LoadErrorBanner
                what="your Claude connection"
                onRetry={loadClaudeSubscription}
                retrying={claudeSubscriptionLoading}
            />
        ) : (
            <LemonSkeleton className="h-16 w-full" />
        )
    }

    return (
        <>
            <div className="divide-y rounded border bg-surface-primary">
                {connected ? (
                    <div className="flex items-center gap-4 px-4 py-3">
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border bg-surface-secondary text-2xl">
                            <IconTerminal />
                        </div>
                        <div className="min-w-0 flex-1">
                            <div className="font-semibold truncate">
                                <span>Claude token&nbsp;</span>
                                <span translate="no">••••{claudeSubscription.token_suffix}</span>
                            </div>
                            <div className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-secondary">
                                {claudeSubscription.connected_at ? (
                                    <span>
                                        <span>Connected </span>
                                        <TZLabel time={claudeSubscription.connected_at} className="align-baseline" />
                                    </span>
                                ) : (
                                    <span>Connected</span>
                                )}
                                {claudeSubscription.last_used_at ? (
                                    <span>
                                        <span>Last used </span>
                                        <TZLabel time={claudeSubscription.last_used_at} className="align-baseline" />
                                    </span>
                                ) : (
                                    <span>Not used yet</span>
                                )}
                            </div>
                        </div>
                        <LemonButton
                            size="small"
                            type="secondary"
                            status="danger"
                            icon={<IconTrash />}
                            onClick={() =>
                                LemonDialog.open({
                                    title: 'Disconnect Claude?',
                                    description: (
                                        <p>
                                            PostHog removes your Claude token. Cloud agent runs that use your Claude
                                            subscription stop working until you connect again.
                                        </p>
                                    ),
                                    primaryButton: {
                                        children: 'Disconnect',
                                        status: 'danger',
                                        onClick: () => disconnectClaudeSubscription(),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }
                            disabledReason={claudeSubscriptionLoading ? 'Loading…' : undefined}
                            tooltip="Disconnect Claude"
                            data-attr="cloud-agents-claude-disconnect"
                        />
                    </div>
                ) : (
                    <div className="px-4 py-6 text-center text-sm text-secondary">
                        <IconTerminal className="text-3xl mb-2 opacity-40" />
                        <p className="mb-0">No Claude subscription connected</p>
                    </div>
                )}
                {!connected && (
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPlus />}
                            onClick={openConnectModal}
                            disabledReason={connecting ? 'Connecting…' : undefined}
                            data-attr="cloud-agents-claude-connect"
                        >
                            Connect Claude
                        </LemonButton>
                        <span className="text-xs text-secondary text-balance">You need a paid Claude plan.</span>
                    </div>
                )}
            </div>
            <ClaudeSubscriptionConnectModal />
        </>
    )
}
