import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonDivider,
    LemonSelect,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

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
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                <TeamsChannelSection />
            </LemonCard>
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
    return (
        <div className="flex items-center justify-between gap-2 py-2 px-3 border rounded">
            <div className="flex-1 min-w-0">
                <div className="font-medium truncate">{pair.team_name || pair.team_id}</div>
                <div className="flex items-center gap-2">
                    <div className="text-xs text-muted-alt truncate">#{pair.channel_name || pair.channel_id}</div>
                    {isShared && (
                        <Tooltip title="Shared channels don't push messages to bots, so PostHog polls them via Microsoft Graph every minute to pick up new messages.">
                            <LemonTag type="completion" size="small">
                                Shared · polled
                            </LemonTag>
                        </Tooltip>
                    )}
                </div>
            </div>
            <LemonButton
                icon={<IconTrash />}
                size="small"
                status="danger"
                onClick={onRemove}
                loading={isLoading}
                disabledReason={adminRestrictionReason || (isLoading ? 'Removing...' : undefined)}
            />
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

    return (
        <div className="flex flex-col gap-2 py-2 px-3 border border-dashed border-muted rounded">
            <div className="flex gap-2 items-center">
                <div className="flex-1">
                    <LemonSelect
                        value={selectedTeamId}
                        options={[
                            { value: null, label: 'Select team group...' },
                            ...teamsTeams.map((t: { id: string; name: string }) => ({
                                value: t.id,
                                label: t.name,
                            })),
                        ]}
                        onChange={handleTeamSelect}
                        loading={teamsTeamsLoading}
                        placeholder="Select team group"
                        fullWidth
                        disabledReason={adminRestrictionReason || undefined}
                    />
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={loadTeamsTeamsWithToken}
                    disabledReason={teamsTeamsLoading ? 'Loading...' : undefined}
                >
                    Refresh
                </LemonButton>
            </div>

            {selectedTeamId && isInstalling && (
                <LemonBanner type="info">Installing SupportHog in the Teams group…</LemonBanner>
            )}

            {selectedTeamId && needsOrgCatalog && (
                <LemonBanner type="warning" className="flex flex-col gap-2">
                    <div>
                        <strong>SupportHog isn't available in your Microsoft tenant's app catalog.</strong> Your
                        organisation's Teams admin needs to upload the SupportHog app package to your{' '}
                        <Link to="https://posthog.com/docs/support/teams#org-catalog" target="_blank">
                            org catalog
                        </Link>{' '}
                        (one-time). Once uploaded, click Retry.
                    </div>
                    <div>
                        <LemonButton type="primary" size="small" onClick={() => installTeamsApp(selectedTeamId)}>
                            Retry install
                        </LemonButton>
                    </div>
                </LemonBanner>
            )}

            {selectedTeamId && installError && (
                <LemonBanner type="error" className="flex flex-col gap-2">
                    <div>Failed to install SupportHog into the selected Teams group.</div>
                    <div>
                        <LemonButton type="primary" size="small" onClick={() => installTeamsApp(selectedTeamId)}>
                            Retry
                        </LemonButton>
                    </div>
                </LemonBanner>
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
                                <LemonSelect
                                    value={null}
                                    options={[
                                        { value: null, label: 'Select channel...' },
                                        ...selectedTeamChannels.map(
                                            (c: { id: string; name: string; membership_type?: string | null }) => {
                                                const isShared = isSharedMembershipType(c.membership_type)
                                                return {
                                                    value: c.id,
                                                    label: isShared ? `#${c.name} (shared)` : `#${c.name}`,
                                                }
                                            }
                                        ),
                                    ]}
                                    onChange={handleChannelSelect}
                                    loading={teamsChannelsLoading || !!teamsChannelPairLoading}
                                    placeholder="Select channel"
                                    fullWidth
                                    disabledReason={adminRestrictionReason || undefined}
                                />
                            </div>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => loadTeamsChannelsForTeam(selectedTeamId)}
                                disabledReason={teamsChannelsLoading ? 'Loading...' : undefined}
                            >
                                Refresh
                            </LemonButton>
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
                    <LemonButton
                        className="mt-2"
                        type="primary"
                        size="small"
                        disabledReason={adminRestrictionReason}
                        onClick={() => connectTeams(window.location.pathname)}
                    >
                        Connect Microsoft Teams
                    </LemonButton>
                )}
            </div>
            {teamsConnected && (
                <>
                    <LemonDivider />
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
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => setShowAddRow(true)}
                                disabledReason={adminRestrictionReason || undefined}
                            >
                                Add Teams channel
                            </LemonButton>
                        )}
                    </div>
                    <LemonDivider />
                    <div className="flex items-center gap-4 justify-between">
                        <div>
                            <label className="font-medium">Bot mention</label>
                            <p className="text-xs text-muted-alt">
                                Users can @mention the bot in any channel to create a support ticket.
                            </p>
                        </div>
                        <LemonTag type="success">Active</LemonTag>
                    </div>
                    <LemonDivider />
                    <div className="flex justify-end">
                        <LemonButton
                            type="secondary"
                            status="danger"
                            size="small"
                            disabledReason={adminRestrictionReason}
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Disconnect Microsoft Teams?',
                                    description:
                                        'This will stop creating tickets from Teams messages. Existing tickets will not be affected.',
                                    primaryButton: {
                                        status: 'danger',
                                        children: 'Disconnect',
                                        onClick: disconnectTeams,
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }}
                        >
                            Disconnect Microsoft Teams
                        </LemonButton>
                    </div>
                </>
            )}
        </div>
    )
}
