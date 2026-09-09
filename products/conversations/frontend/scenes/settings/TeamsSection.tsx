import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconTrash } from '@posthog/icons'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
    Badge,
    Button,
    Card,
    CardContent,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Separator,
    Spinner,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { supportSettingsLogic } from './supportSettingsLogic'

// Graph reports shared channels as "shared" or, in some tenants, "unknownFutureValue".
// Anything that isn't an explicit standard/private channel is polled (shared).
function isSharedMembershipType(membershipType: string | null | undefined): boolean {
    return membershipType != null && !['standard', 'private'].includes(membershipType)
}

export function TeamsSection(): JSX.Element {
    return (
        <SceneSection
            title="Microsoft Teams"
            description={
                <>
                    Connect the SupportHog bot to Microsoft Teams to create and manage support tickets from Teams
                    channel messages and @mentions.{' '}
                    <Link to="https://posthog.com/docs/support/teams" target="_blank">
                        Docs
                    </Link>
                </>
            }
        >
            <Card size="sm" className="max-w-[800px]">
                <CardContent>
                    <TeamsChannelSection />
                </CardContent>
            </Card>
        </SceneSection>
    )
}

interface TeamsChannelRowProps {
    pair: {
        team_id: string
        team_name?: string | null
        channel_id: string
        channel_name?: string | null
        membership_type?: string | null
    }
    onRemove: () => void
    isLoading: boolean
    adminRestrictionReason: string | null
}

function TeamsChannelRow({ pair, onRemove, isLoading, adminRestrictionReason }: TeamsChannelRowProps): JSX.Element {
    const isShared = isSharedMembershipType(pair.membership_type)
    const removeDisabledReason = adminRestrictionReason || (isLoading ? 'Removing...' : undefined)
    return (
        <div className="flex items-center justify-between gap-2 py-2 px-3 border rounded">
            <div className="flex-1 min-w-0">
                <div className="font-medium truncate">{pair.team_name || pair.team_id}</div>
                <div className="flex items-center gap-2">
                    <div className="text-xs text-muted-alt truncate">#{pair.channel_name || pair.channel_id}</div>
                    {isShared && (
                        <Tooltip>
                            <TooltipTrigger render={<Badge variant="completed" />}>Shared · polled</TooltipTrigger>
                            <TooltipContent>
                                Shared channels don't push messages to bots, so PostHog polls them via Microsoft Graph
                                every minute to pick up new messages.
                            </TooltipContent>
                        </Tooltip>
                    )}
                </div>
            </div>
            <Button
                variant="destructive"
                size="icon-sm"
                onClick={onRemove}
                loading={isLoading}
                disabled={!!removeDisabledReason}
                title={removeDisabledReason}
                aria-label="Remove channel"
            >
                <IconTrash />
            </Button>
        </div>
    )
}

interface AddTeamsChannelRowProps {
    adminRestrictionReason: string | null
}

function AddTeamsChannelRow({ adminRestrictionReason }: AddTeamsChannelRowProps): JSX.Element {
    const {
        teamsTeams,
        teamsTeamsLoading,
        teamsChannelsLoading,
        teamsInstallStatus,
        teamsInstallingForTeamId,
        teamsChannelsCache,
        teamsChannelPairLoading,
        teamsChannelPairs,
    } = useValues(supportSettingsLogic)
    const { loadTeamsTeamsWithToken, loadTeamsChannelsForTeam, installTeamsApp, addTeamsChannelPair } =
        useActions(supportSettingsLogic)

    const [selectedTeamId, setSelectedTeamId] = useState<string | null>(null)

    // Install status is a single global value; only apply it to the row when it refers to the selected team.
    const statusForSelected =
        selectedTeamId && teamsInstallingForTeamId === selectedTeamId ? teamsInstallStatus : 'idle'
    const isInstalling = statusForSelected === 'installing'
    const needsOrgCatalog = statusForSelected === 'needs_org_catalog'
    const installError = statusForSelected === 'error'
    const appInstalled = statusForSelected === 'installed'

    // Exclude channels already configured (prevent duplicates in the picker).
    const configuredChannelIds = new Set(teamsChannelPairs.map((p) => p.channel_id))
    const allSelectedTeamChannels = selectedTeamId ? teamsChannelsCache[selectedTeamId] || [] : []
    const selectedTeamChannels = allSelectedTeamChannels.filter((c: { id: string }) => !configuredChannelIds.has(c.id))

    const handleTeamSelect = (teamId: string | null): void => {
        setSelectedTeamId(teamId)
        // installTeamsApp loads the team's channels on success (and is idempotent server-side).
        if (teamId) {
            installTeamsApp(teamId)
        }
    }

    const handleChannelSelect = (channelId: string | null): void => {
        if (channelId && selectedTeamId) {
            addTeamsChannelPair(selectedTeamId, channelId)
            setSelectedTeamId(null)
        }
    }

    const teamsLoadingReason = teamsTeamsLoading ? 'Loading...' : undefined
    const channelsLoadingReason = teamsChannelsLoading ? 'Loading...' : undefined

    return (
        <div className="flex flex-col gap-2 py-2 px-3 border border-dashed border-muted rounded">
            <div className="flex gap-2 items-center">
                <div className="flex-1">
                    <Select
                        value={selectedTeamId}
                        onValueChange={(teamId) => handleTeamSelect(teamId)}
                        disabled={!!adminRestrictionReason}
                    >
                        <SelectTrigger
                            className="w-full"
                            title={adminRestrictionReason ?? undefined}
                            aria-busy={teamsTeamsLoading}
                        >
                            {teamsTeamsLoading ? <Spinner /> : null}
                            <SelectValue placeholder="Select team group" />
                        </SelectTrigger>
                        <SelectContent>
                            {teamsTeams.map((t: { id: string; name: string }) => (
                                <SelectItem key={t.id} value={t.id}>
                                    {t.name}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={loadTeamsTeamsWithToken}
                    disabled={!!teamsLoadingReason}
                    title={teamsLoadingReason}
                >
                    Refresh
                </Button>
            </div>

            {selectedTeamId && isInstalling && (
                <div className="rounded border border-primary bg-surface-secondary p-2 text-sm">
                    Installing SupportHog in the Teams group…
                </div>
            )}

            {selectedTeamId && needsOrgCatalog && (
                <div className="rounded border border-warning bg-warning-highlight p-2 text-sm flex flex-col gap-2">
                    <div>
                        <strong>SupportHog isn't available in your Microsoft tenant's app catalog.</strong> Your
                        organisation's Teams admin needs to upload the SupportHog app package to your{' '}
                        <Link to="https://posthog.com/docs/support/teams#org-catalog" target="_blank">
                            org catalog
                        </Link>{' '}
                        (one-time). Once uploaded, click Retry.
                    </div>
                    <div>
                        <Button variant="primary" size="sm" onClick={() => installTeamsApp(selectedTeamId)}>
                            Retry install
                        </Button>
                    </div>
                </div>
            )}

            {selectedTeamId && installError && (
                <div className="rounded border border-danger bg-danger-highlight p-2 text-sm flex flex-col gap-2">
                    <div>Failed to install SupportHog into the selected Teams group.</div>
                    <div>
                        <Button variant="primary" size="sm" onClick={() => installTeamsApp(selectedTeamId)}>
                            Retry
                        </Button>
                    </div>
                </div>
            )}

            {selectedTeamId && appInstalled && (
                <>
                    {selectedTeamChannels.length === 0 && !teamsChannelsLoading ? (
                        <p className="text-xs text-muted-alt italic">
                            All channels in this group are already configured.
                        </p>
                    ) : (
                        <div className="flex gap-2 items-center">
                            <div className="flex-1">
                                <Select
                                    value={null}
                                    onValueChange={handleChannelSelect}
                                    disabled={!!adminRestrictionReason}
                                >
                                    <SelectTrigger
                                        className="w-full"
                                        title={adminRestrictionReason ?? undefined}
                                        aria-busy={teamsChannelsLoading || !!teamsChannelPairLoading}
                                    >
                                        {teamsChannelsLoading || !!teamsChannelPairLoading ? <Spinner /> : null}
                                        <SelectValue placeholder="Select channel" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {selectedTeamChannels.map(
                                            (c: { id: string; name: string; membership_type?: string | null }) => {
                                                const isShared = isSharedMembershipType(c.membership_type)
                                                return (
                                                    <SelectItem key={c.id} value={c.id}>
                                                        {isShared ? `#${c.name} (shared)` : `#${c.name}`}
                                                    </SelectItem>
                                                )
                                            }
                                        )}
                                    </SelectContent>
                                </Select>
                            </div>
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => loadTeamsChannelsForTeam(selectedTeamId)}
                                disabled={!!channelsLoadingReason}
                                title={channelsLoadingReason}
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

function TeamsChannelSection(): JSX.Element {
    const { teamsConnected, teamsChannelPairs, teamsChannelPairLoading } = useValues(supportSettingsLogic)
    const { connectTeams, disconnectTeams, removeTeamsChannelPair } = useActions(supportSettingsLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const [showAddRow, setShowAddRow] = useState(false)

    return (
        <div className="flex flex-col gap-y-2">
            <div>
                <label className="font-medium">Connection</label>
                <p className="text-xs text-muted-alt">
                    Connect your Microsoft Teams tenant to enable support ticket creation from channel messages and
                    @mentions. Requires a Teams admin to authorize the SupportHog app.
                </p>
                {!teamsConnected && (
                    <Button
                        className="mt-2"
                        variant="primary"
                        size="sm"
                        disabled={!!adminRestrictionReason}
                        title={adminRestrictionReason ?? undefined}
                        onClick={() => connectTeams(window.location.pathname)}
                    >
                        Connect Microsoft Teams
                    </Button>
                )}
            </div>
            {teamsConnected && (
                <>
                    <Separator />
                    <div className="flex flex-col gap-2">
                        <div>
                            <label className="font-medium">Support channels</label>
                            <p className="text-xs text-muted-alt">
                                Messages posted in these channels will automatically create support tickets. Thread
                                replies become ticket messages.
                            </p>
                        </div>

                        {teamsChannelPairs.length > 0 && (
                            <div className="flex flex-col gap-2">
                                {teamsChannelPairs.map((pair) => (
                                    <TeamsChannelRow
                                        key={pair.channel_id}
                                        pair={pair}
                                        onRemove={() => removeTeamsChannelPair(pair.channel_id)}
                                        isLoading={teamsChannelPairLoading === pair.channel_id}
                                        adminRestrictionReason={adminRestrictionReason}
                                    />
                                ))}
                            </div>
                        )}

                        {showAddRow ? (
                            <AddTeamsChannelRow adminRestrictionReason={adminRestrictionReason} />
                        ) : (
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => setShowAddRow(true)}
                                disabled={!!adminRestrictionReason}
                                title={adminRestrictionReason ?? undefined}
                            >
                                Add Teams channel
                            </Button>
                        )}
                    </div>
                    <Separator />
                    <div className="flex items-center gap-4 justify-between">
                        <div>
                            <label className="font-medium">Bot mention</label>
                            <p className="text-xs text-muted-alt">
                                Users can @mention the bot in any channel to create a support ticket.
                            </p>
                        </div>
                        <Badge variant="success">Active</Badge>
                    </div>
                    <Separator />
                    <div className="flex justify-end">
                        <AlertDialog>
                            <AlertDialogTrigger
                                render={
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        disabled={!!adminRestrictionReason}
                                        title={adminRestrictionReason ?? undefined}
                                    />
                                }
                            >
                                Disconnect Microsoft Teams
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                                <AlertDialogHeader>
                                    <AlertDialogTitle>Disconnect Microsoft Teams?</AlertDialogTitle>
                                    <AlertDialogDescription>
                                        This will stop creating tickets from Teams messages. Existing tickets will not
                                        be affected.
                                    </AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                    <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                                    <AlertDialogClose
                                        render={<Button variant="destructive" onClick={disconnectTeams} />}
                                    >
                                        Disconnect
                                    </AlertDialogClose>
                                </AlertDialogFooter>
                            </AlertDialogContent>
                        </AlertDialog>
                    </div>
                </>
            )}
        </div>
    )
}
