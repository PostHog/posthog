import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCard, LemonDivider, LemonSelect, LemonTag, Link } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { supportSettingsLogic } from './supportSettingsLogic'

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

function TeamsChannelSection(): JSX.Element {
    const {
        teamsConnected,
        teamsTeamId,
        teamsTeams,
        teamsTeamsLoading,
        teamsChannelId,
        teamsChannels,
        teamsChannelsLoading,
        teamsInstallStatus,
    } = useValues(supportSettingsLogic)
    const {
        connectTeams,
        disconnectTeams,
        setTeamsTeam,
        setTeamsChannel,
        loadTeamsTeamsWithToken,
        loadTeamsChannelsForTeam,
        installTeamsApp,
    } = useActions(supportSettingsLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

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
                    <div className="gap-4">
                        <div>
                            <label className="font-medium">Teams group</label>
                            <p className="text-xs text-muted-alt">
                                Select the Microsoft Teams group that contains your support channel.
                            </p>
                        </div>
                        <div className="flex gap-2 items-center">
                            <LemonSelect
                                value={teamsTeamId}
                                options={[
                                    { value: null, label: 'None' },
                                    ...teamsTeams.map((t: { id: string; name: string }) => ({
                                        value: t.id,
                                        label: t.name,
                                    })),
                                ]}
                                onChange={(value) => {
                                    const team = teamsTeams.find((t: { id: string }) => t.id === value)
                                    setTeamsTeam(value, team?.name ?? null)
                                }}
                                loading={teamsTeamsLoading}
                                placeholder="Select team"
                            />
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={loadTeamsTeamsWithToken}
                                disabledReason={teamsTeamsLoading ? 'Loading teams...' : undefined}
                            >
                                Refresh
                            </LemonButton>
                        </div>
                    </div>
                    {teamsTeamId && teamsInstallStatus === 'installing' && (
                        <>
                            <LemonDivider />
                            <LemonBanner type="info">Installing SupportHog in your Teams group…</LemonBanner>
                        </>
                    )}
                    {teamsTeamId && teamsInstallStatus === 'needs_org_catalog' && (
                        <>
                            <LemonDivider />
                            <LemonBanner type="warning" className="flex flex-col gap-2">
                                <div>
                                    <strong>SupportHog isn't available in your Microsoft tenant's app catalog.</strong>{' '}
                                    Your organisation's Teams admin needs to upload the SupportHog app package to your{' '}
                                    <Link to="https://posthog.com/docs/support/teams#org-catalog" target="_blank">
                                        org catalog
                                    </Link>{' '}
                                    (one-time). Once uploaded, click Retry.
                                </div>
                                <div>
                                    <LemonButton
                                        type="primary"
                                        size="small"
                                        onClick={() => installTeamsApp(teamsTeamId)}
                                    >
                                        Retry install
                                    </LemonButton>
                                </div>
                            </LemonBanner>
                        </>
                    )}
                    {teamsTeamId && teamsInstallStatus === 'error' && (
                        <>
                            <LemonDivider />
                            <LemonBanner type="error" className="flex flex-col gap-2">
                                <div>Failed to install SupportHog into the selected Teams group.</div>
                                <div>
                                    <LemonButton
                                        type="primary"
                                        size="small"
                                        onClick={() => installTeamsApp(teamsTeamId)}
                                    >
                                        Retry
                                    </LemonButton>
                                </div>
                            </LemonBanner>
                        </>
                    )}
                    {teamsTeamId && teamsInstallStatus === 'installed' && (
                        <>
                            <LemonDivider />
                            <div className="gap-4">
                                <div>
                                    <label className="font-medium">Support channel</label>
                                    <p className="text-xs text-muted-alt">
                                        Messages posted in this channel will automatically create support tickets.
                                        Thread replies become ticket messages.
                                    </p>
                                </div>
                                <div className="flex gap-2 items-center">
                                    <LemonSelect
                                        value={teamsChannelId}
                                        options={[
                                            { value: null, label: 'None' },
                                            ...teamsChannels.map((c: { id: string; name: string }) => ({
                                                value: c.id,
                                                label: c.name,
                                            })),
                                        ]}
                                        onChange={(value) => {
                                            const channel = teamsChannels.find((c: { id: string }) => c.id === value)
                                            setTeamsChannel(value, channel?.name ?? null)
                                        }}
                                        loading={teamsChannelsLoading}
                                        placeholder="Select channel"
                                    />
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        onClick={() => {
                                            if (teamsTeamId) {
                                                loadTeamsChannelsForTeam(teamsTeamId)
                                            }
                                        }}
                                        disabledReason={teamsChannelsLoading ? 'Loading channels...' : undefined}
                                    >
                                        Refresh
                                    </LemonButton>
                                </div>
                            </div>
                        </>
                    )}
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
