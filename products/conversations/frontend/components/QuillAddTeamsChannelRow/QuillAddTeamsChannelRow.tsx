import {
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

export interface QuillTeamsSelectOption {
    value: string | null
    label: string
}

export function QuillAddTeamsChannelRow({
    selectedTeamId,
    teamOptions,
    channelOptions,
    teamsLoading,
    channelsLoading,
    isInstalling,
    needsOrgCatalog,
    installError,
    appInstalled,
    allChannelsConfigured,
    adminRestrictionReason,
    onTeamSelect,
    onChannelSelect,
    onRefreshTeams,
    onRetryInstall,
    onRefreshChannels,
}: {
    selectedTeamId: string | null
    teamOptions: QuillTeamsSelectOption[]
    channelOptions: QuillTeamsSelectOption[]
    teamsLoading: boolean
    channelsLoading: boolean
    isInstalling: boolean
    needsOrgCatalog: boolean
    installError: boolean
    appInstalled: boolean
    allChannelsConfigured: boolean
    adminRestrictionReason: string | null
    onTeamSelect: (teamId: string | null) => void
    onChannelSelect: (channelId: string | null) => void
    onRefreshTeams: () => void
    onRetryInstall: () => void
    onRefreshChannels: () => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2 rounded-md border border-dashed p-3">
            <div className="flex flex-wrap items-center gap-2">
                <Select<string | null> items={teamOptions} value={selectedTeamId} onValueChange={onTeamSelect}>
                    <SelectTrigger
                        className="min-w-0 flex-1"
                        aria-label="Select team group"
                        disabledReason={adminRestrictionReason || (teamsLoading ? 'Loading...' : undefined)}
                    >
                        <SelectValue placeholder="Select team group" />
                    </SelectTrigger>
                    <SelectContent>
                        {teamOptions.map((option) => (
                            <SelectItem key={option.value ?? 'none'} value={option.value}>
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <Button
                    variant="outline"
                    onClick={onRefreshTeams}
                    disabledReason={adminRestrictionReason || (teamsLoading ? 'Loading...' : undefined)}
                >
                    Refresh
                </Button>
            </div>

            {selectedTeamId && isInstalling && (
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>Installing SupportHog in the Teams group…</ItemDescription>
                    </ItemContent>
                </Item>
            )}

            {selectedTeamId && needsOrgCatalog && (
                <Item tone="warning" size="sm">
                    <ItemContent>
                        <ItemTitle>SupportHog isn't available in your Microsoft tenant's app catalog.</ItemTitle>
                        <ItemDescription>
                            Your organisation's Teams admin needs to upload the SupportHog app package to your{' '}
                            <Button
                                variant="link"
                                size="inline"
                                nativeButton={false}
                                render={
                                    <LinkPrimitive
                                        to="https://posthog.com/docs/support/teams#org-catalog"
                                        target="_blank"
                                    />
                                }
                            >
                                org catalog
                            </Button>{' '}
                            (one-time). Once uploaded, click Retry.
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button variant="primary" onClick={onRetryInstall}>
                            Retry install
                        </Button>
                    </ItemActions>
                </Item>
            )}

            {selectedTeamId && installError && (
                <Item tone="destructive" size="sm">
                    <ItemContent>
                        <ItemDescription>Failed to install SupportHog into the selected Teams group.</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button variant="primary" onClick={onRetryInstall}>
                            Retry
                        </Button>
                    </ItemActions>
                </Item>
            )}

            {selectedTeamId && appInstalled && (
                <>
                    {allChannelsConfigured ? (
                        <Text size="xs" variant="muted" render={<p className="m-0 italic" />}>
                            All channels in this group are already configured.
                        </Text>
                    ) : (
                        <div className="flex flex-wrap items-center gap-2">
                            <Select<string | null> items={channelOptions} value={null} onValueChange={onChannelSelect}>
                                <SelectTrigger
                                    className="min-w-0 flex-1"
                                    aria-label="Select channel"
                                    disabledReason={
                                        adminRestrictionReason || (channelsLoading ? 'Loading...' : undefined)
                                    }
                                >
                                    <SelectValue placeholder="Select channel" />
                                </SelectTrigger>
                                <SelectContent>
                                    {channelOptions.map((option) => (
                                        <SelectItem key={option.value ?? 'none'} value={option.value}>
                                            {option.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            <Button
                                variant="outline"
                                onClick={onRefreshChannels}
                                disabledReason={channelsLoading ? 'Loading...' : undefined}
                            >
                                Refresh
                            </Button>
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
