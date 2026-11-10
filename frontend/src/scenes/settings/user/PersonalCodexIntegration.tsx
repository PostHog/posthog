import { useActions, useValues } from 'kea'

import { IconPlus, IconTerminal, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { CodexIntegrationStatusEnumApi, type UserCodexIntegrationApi } from '~/generated/core/api.schemas'

import { CodexConnectModal, SETTINGS_CODEX_CONNECT_OPENER } from './CodexConnectModal'
import { personalCodexIntegrationLogic } from './personalCodexIntegrationLogic'

function CodexAccountRow({ integration }: { integration: UserCodexIntegrationApi }): JSX.Element {
    const { disconnectCodex } = useActions(personalCodexIntegrationLogic)
    const { codexIntegrationLoading } = useValues(personalCodexIntegrationLogic)

    const handleDisconnect = (): void => {
        LemonDialog.open({
            title: 'Disconnect Codex?',
            description: (
                <p>
                    PostHog removes your ChatGPT sign-in. Codex cloud tasks that use your ChatGPT plan stop working
                    until you connect again.
                </p>
            ),
            primaryButton: {
                children: 'Disconnect',
                status: 'danger',
                onClick: () => disconnectCodex(),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex items-center gap-4 px-4 py-3">
            <div className="shrink-0">
                <div className="flex h-10 w-10 items-center justify-center rounded-md border bg-surface-secondary text-2xl">
                    <IconTerminal />
                </div>
            </div>
            <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold truncate">{integration.email || 'ChatGPT account'}</span>
                    {integration.plan_type ? (
                        <LemonTag type="muted" className="capitalize">
                            {`ChatGPT ${integration.plan_type}`}
                        </LemonTag>
                    ) : null}
                </div>
                <div className="mt-0.5 text-xs text-secondary">
                    {integration.connected_at ? (
                        <>
                            <span>Connected </span>
                            <TZLabel time={integration.connected_at} className="align-baseline" />
                        </>
                    ) : (
                        'Connected'
                    )}
                </div>
                {integration.status === CodexIntegrationStatusEnumApi.ReauthRequired ? (
                    <LemonBanner type="error" className="mt-2">
                        Your ChatGPT sign-in stopped working. Connect Codex again to keep using your ChatGPT plan.
                    </LemonBanner>
                ) : null}
            </div>
            <div className="flex shrink-0 items-center">
                <LemonButton
                    size="small"
                    type="secondary"
                    status="danger"
                    icon={<IconTrash />}
                    onClick={handleDisconnect}
                    disabledReason={codexIntegrationLoading ? 'Loading…' : undefined}
                    tooltip="Disconnect Codex"
                    data-attr="codex-disconnect"
                />
            </div>
        </div>
    )
}

export function PersonalCodexIntegration(): JSX.Element {
    const { codexIntegration, codexIntegrationLoadFailed, connecting } = useValues(personalCodexIntegrationLogic)
    const { openConnectModal } = useActions(personalCodexIntegrationLogic)

    if (codexIntegration === null) {
        return codexIntegrationLoadFailed ? (
            <LemonBanner type="error">Could not load your Codex connection. Refresh the page to try again.</LemonBanner>
        ) : (
            <LemonSkeleton className="h-16 w-full" />
        )
    }

    const notConnected = codexIntegration.status === CodexIntegrationStatusEnumApi.NotConnected
    const reauthRequired = codexIntegration.status === CodexIntegrationStatusEnumApi.ReauthRequired

    return (
        <>
            <div className="divide-y rounded border bg-surface-primary">
                {notConnected ? (
                    <div className="px-4 py-6 text-center text-sm text-secondary">
                        <IconTerminal className="text-3xl mb-2 opacity-40" />
                        <p className="mb-0">No Codex account connected</p>
                    </div>
                ) : (
                    <CodexAccountRow integration={codexIntegration} />
                )}
                {notConnected || reauthRequired ? (
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPlus />}
                            onClick={() => openConnectModal(SETTINGS_CODEX_CONNECT_OPENER)}
                            disabledReason={connecting ? 'Connecting…' : undefined}
                            data-attr="codex-connect"
                        >
                            {reauthRequired ? 'Connect again' : 'Connect Codex'}
                        </LemonButton>
                        <span className="text-xs text-secondary text-balance">You need a paid ChatGPT plan.</span>
                    </div>
                ) : null}
            </div>
            <CodexConnectModal opener={SETTINGS_CODEX_CONNECT_OPENER} />
        </>
    )
}
