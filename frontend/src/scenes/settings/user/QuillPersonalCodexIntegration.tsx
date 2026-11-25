import { useActions, useValues } from 'kea'

import { IconPlus, IconTerminal, IconTrash } from '@posthog/icons'
import {
    Badge,
    Button,
    Empty,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { CodexIntegrationStatusEnumApi, type UserCodexIntegrationApi } from '~/generated/core/api.schemas'

import { SETTINGS_CODEX_CONNECT_OPENER } from './CodexConnectModal'
import { confirmCodexDisconnect } from './confirmCodexDisconnect'
import { personalCodexIntegrationLogic } from './personalCodexIntegrationLogic'
import { QuillCodexConnectModal } from './QuillCodexConnectModal'

function QuillCodexAccountRow({ integration }: { integration: UserCodexIntegrationApi }): JSX.Element {
    const { disconnectCodex } = useActions(personalCodexIntegrationLogic)
    const { codexIntegrationLoading } = useValues(personalCodexIntegrationLogic)

    return (
        <div className="flex flex-col gap-2">
            <Item variant="outline">
                <ItemMedia variant="icon">
                    <IconTerminal />
                </ItemMedia>
                <ItemContent className="min-w-0">
                    <ItemTitle className="flex flex-wrap items-center gap-2">
                        <span className="truncate">{integration.email || 'ChatGPT account'}</span>
                        {integration.plan_type ? (
                            <Badge className="capitalize">{`ChatGPT ${integration.plan_type}`}</Badge>
                        ) : null}
                    </ItemTitle>
                    <ItemDescription>
                        {integration.connected_at ? (
                            <>
                                <span>Connected </span>
                                <TZLabel time={integration.connected_at} className="align-baseline" />
                            </>
                        ) : (
                            'Connected'
                        )}
                    </ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Button
                        variant="destructive-outline"
                        size="icon"
                        aria-label="Disconnect Codex"
                        tooltip="Disconnect Codex"
                        onClick={() => confirmCodexDisconnect(disconnectCodex)}
                        disabledReason={codexIntegrationLoading ? 'Loading…' : undefined}
                        data-attr="codex-disconnect"
                    >
                        <IconTrash />
                    </Button>
                </ItemActions>
            </Item>
            {integration.status === CodexIntegrationStatusEnumApi.ReauthRequired ? (
                <Item tone="destructive" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            Your ChatGPT sign-in stopped working. Connect Codex again to keep using your ChatGPT plan.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            ) : null}
        </div>
    )
}

export function QuillPersonalCodexIntegration(): JSX.Element {
    const { codexIntegration, codexIntegrationLoadFailed, connecting } = useValues(personalCodexIntegrationLogic)
    const { openConnectModal } = useActions(personalCodexIntegrationLogic)

    if (codexIntegration === null) {
        return codexIntegrationLoadFailed ? (
            <Item tone="destructive" size="sm">
                <ItemContent>
                    <ItemDescription>
                        Could not load your Codex connection. Refresh the page to try again.
                    </ItemDescription>
                </ItemContent>
            </Item>
        ) : (
            <Skeleton className="h-16 w-full" />
        )
    }

    const notConnected = codexIntegration.status === CodexIntegrationStatusEnumApi.NotConnected
    const reauthRequired = codexIntegration.status === CodexIntegrationStatusEnumApi.ReauthRequired

    return (
        <div className="flex flex-col gap-2">
            {notConnected ? (
                <Empty>
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconTerminal />
                        </EmptyMedia>
                        <EmptyTitle>No Codex account connected</EmptyTitle>
                    </EmptyHeader>
                </Empty>
            ) : (
                <QuillCodexAccountRow integration={codexIntegration} />
            )}
            {notConnected || reauthRequired ? (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    <Button
                        variant="outline"
                        onClick={() => openConnectModal(SETTINGS_CODEX_CONNECT_OPENER)}
                        disabledReason={connecting ? 'Connecting…' : undefined}
                        data-attr="codex-connect"
                    >
                        <IconPlus />
                        <span>{reauthRequired ? 'Connect again' : 'Connect Codex'}</span>
                    </Button>
                    <Text size="xs" variant="muted" render={<span />}>
                        You need a paid ChatGPT plan.
                    </Text>
                </div>
            ) : null}
            <QuillCodexConnectModal opener={SETTINGS_CODEX_CONNECT_OPENER} />
        </div>
    )
}
