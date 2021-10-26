import React, { useState } from 'react'
import { BindLogic, useActions, useValues } from 'kea'
import { Button, Card, Divider, Input, Skeleton, Tag } from 'antd'
import { IPCapture } from './IPCapture'
import { JSSnippet } from 'lib/components/JSSnippet'
import { SessionRecording } from './SessionRecording'
import { EditAppUrls } from 'lib/components/AppEditorLink/EditAppUrls'
import { WebhookIntegration } from './WebhookIntegration'
import { useAnchor } from 'lib/hooks/useAnchor'
import { router } from 'kea-router'
import { ReloadOutlined } from '@ant-design/icons'
import { red } from '@ant-design/colors'
import { ToolbarSettings } from './ToolbarSettings'
import { CodeSnippet } from 'scenes/ingestion/frameworks/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'
import { DangerZone } from './DangerZone'
import { PageHeader } from 'lib/components/PageHeader'
import { Link } from 'lib/components/Link'
import { JSBookmarklet } from 'lib/components/JSBookmarklet'
import { RestrictedArea, RestrictionScope } from '../../../lib/components/RestrictedArea'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from '../../../lib/constants'
import { TestAccountFiltersConfig } from './TestAccountFiltersConfig'
import { TimezoneConfig } from './TimezoneConfig'
import { DataAttributes } from 'scenes/project/Settings/DataAttributes'
import { featureFlagLogic } from '../../../lib/logic/featureFlagLogic'
import { AvailableFeature, UserType } from '../../../types'
import { TeamMembers } from './TeamMembers'
import { teamMembersLogic } from './teamMembersLogic'
import { AccessControl } from './AccessControl'
import { PathCleaningFiltersConfig } from './PathCleaningFiltersConfig'
import { userLogic } from 'scenes/userLogic'

function DisplayName(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const [name, setName] = useState(currentTeam?.name || '')

    if (currentTeam?.is_demo) {
        return (
            <p>
                <i>The demo project cannot be renamed.</i>
            </p>
        )
    }

    return (
        <div>
            <Input
                value={name}
                onChange={(event) => {
                    setName(event.target.value)
                }}
                style={{ maxWidth: '40rem', marginBottom: '1rem', display: 'block' }}
                disabled={currentTeamLoading}
            />
            <Button
                type="primary"
                onClick={(e) => {
                    e.preventDefault()
                    updateCurrentTeam({ name })
                }}
                disabled={!name || !currentTeam || name === currentTeam.name}
                loading={currentTeamLoading}
            >
                Rename Project
            </Button>
        </div>
    )
}

export function ProjectSettings({ user }: { user: UserType }): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { resetToken } = useActions(teamLogic)
    const { location } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    useAnchor(location.hash)

    const loadingComponent = <Skeleton active />

    return (
        <div style={{ marginBottom: 128 }}>
            <PageHeader
                title="Project Settings"
                caption={`Organize your analytics within the project. These settings only apply to ${
                    currentTeam?.name ?? 'the current project'
                }.`}
            />
            <Card>
                <h2 id="name" className="subtitle">
                    Display Name
                </h2>
                {currentTeamLoading && !currentTeam ? loadingComponent : <DisplayName />}
                <Divider />
                <h2 id="snippet" className="subtitle">
                    Website Event Autocapture
                </h2>
                To integrate PostHog into your website and get event autocapture with no additional work, include the
                following snippet in your&nbsp;website's&nbsp;HTML. Ideally, put it just above the&nbsp;
                <code>{'</head>'}</code>&nbsp;tag.
                <br />
                For more guidance, including on identifying users,{' '}
                <a href="https://posthog.com/docs/integrations/js-integration">see PostHog Docs</a>.
                {currentTeamLoading && !currentTeam ? loadingComponent : <JSSnippet />}
                <p>
                    You can even test PostHog out on a live site without changing any code.
                    <br />
                    Just drag the bookmarklet below to your bookmarks bar, open the website you want to test PostHog on
                    and click it.
                    <br />
                    This will enable our tracking, on the currently loaded page only. The data will show up in this
                    project.
                    <br />
                </p>
                <div>{currentTeam && <JSBookmarklet team={currentTeam} />}</div>
                <Divider />
                <h2 id="custom-events" className="subtitle">
                    Send Custom Events
                </h2>
                To send custom events <a href="https://posthog.com/docs/integrations">visit PostHog Docs</a> and
                integrate the library for the specific language or platform you're using. We support Python, Ruby, Node,
                Go, PHP, iOS, Android, and more.
                <Divider />
                <h2 id="project-api-key" className="subtitle">
                    Project API Key
                </h2>
                You can use this write-only key in any one of{' '}
                <a href="https://posthog.com/docs/integrations">our libraries</a>.
                <CodeSnippet
                    actions={[
                        {
                            Icon: ReloadOutlined,
                            title: 'Reset Project API Key',
                            popconfirmProps: {
                                title: (
                                    <>
                                        Reset the project's API key?{' '}
                                        <b>This will invalidate the current API key and cannot be undone.</b>
                                    </>
                                ),
                                okText: 'Reset Key',
                                okType: 'danger',
                                icon: <ReloadOutlined style={{ color: red.primary }} />,
                                placement: 'left',
                            },
                            callback: resetToken,
                        },
                    ]}
                    copyDescription="project API key"
                >
                    {currentTeam?.api_token || ''}
                </CodeSnippet>
                Write-only means it can only create new events. It can't read events or any of your other data stored
                with PostHog, so it's safe to use in public apps.
                <Divider />
                <h2 className="subtitle" id="timezone">
                    Timezone
                </h2>
                <p>Set the timezone for your project so that you can see relevant time conversions in PostHog.</p>
                <TimezoneConfig />
                <Divider />
                <h2 className="subtitle" id="internal-users-filtering">
                    Filter Out Internal and Test Users
                </h2>
                <p>
                    Increase the quality of your analytics results by filtering out events from internal sources, such
                    as team members, test accounts, or development environments.
                </p>
                <p>
                    <b>Events will still be ingested and saved</b> (and will count towards any totals), they will
                    however be excluded from consideration on any queries where the "Filter out internal and test users"
                    toggle is set.
                </p>
                <p>
                    Example filters to use below: <i>email ∌ yourcompany.com</i> to exclude all events from your
                    company's team members, or <i>Host ∌ localhost</i> to exclude all events from local development
                    environments.
                </p>
                <p>
                    <b>The filters you apply here are added as extra filters when the toggle is switched on.</b> So, if
                    you apply a Cohort filter, it means toggling filtering on will match only this specific cohort.
                </p>
                <TestAccountFiltersConfig />
                <Divider />
                <h2 className="subtitle" id="path_cleaning_filtering">
                    Path Cleaning Rules
                </h2>
                <p>Reduce noisy parameters in your path results by performing replacement using regex matching.</p>
                <p>
                    Each rule is composed of an alias and a regex pattern. Any pattern in a URL or event name that
                    matches the regex will be replaced with the alias.
                </p>
                <p>The rules are applied in the order that they're listed.</p>
                <p>
                    <b>
                        Rules that you set here will be applied before wildcarding and other regex replacement if the
                        toggle is switched on.
                    </b>
                </p>
                <PathCleaningFiltersConfig />
                <Divider />
                <h2 className="subtitle" id="urls">
                    Permitted Domains/URLs
                </h2>
                <p>
                    These are the domains and URLs where the <b>Toolbar will automatically launch</b> (if you're logged
                    in) and where we'll <a href="#session-recording">record sessions</a> (if enabled).
                </p>
                <EditAppUrls />
                <Divider />
                <h2 className="subtitle" id="attributes">
                    Data Attributes
                </h2>
                <DataAttributes />
                <Divider />
                <h2 className="subtitle" id="webhook">
                    Webhook Integration
                </h2>
                <WebhookIntegration />
                <Divider />
                <h2 className="subtitle" id="datacapture">
                    Data Capture Configuration
                </h2>
                <IPCapture />
                <Divider />
                <h2 className="subtitle">PostHog Toolbar</h2>
                <ToolbarSettings />
                <Divider />
                <div id="session-recording" />
                <h2 id="recordings" className="subtitle" style={{ display: 'flex', alignItems: 'center' }}>
                    Recordings
                    <Tag color="orange" style={{ marginLeft: 8 }}>
                        BETA
                    </Tag>
                </h2>
                <p>
                    Watch replays to see how users interact with your app and find out what can be improved. Recordings
                    are found in the{' '}
                    <Link to={featureFlags[FEATURE_FLAGS.REMOVE_SESSIONS] ? '/recordings' : '/sessions'}>
                        {featureFlags[FEATURE_FLAGS.REMOVE_SESSIONS] ? 'recordings' : 'sessions'} page
                    </Link>
                    . Please note <b>your website needs to have</b> the <a href="#snippet">PostHog snippet</a> or the
                    latest version of{' '}
                    <a
                        href="https://posthog.com/docs/integrations/js-integration?utm_campaign=session-recording&utm_medium=in-product"
                        target="_blank"
                    >
                        posthog-js
                    </a>{' '}
                    <b>directly</b> installed. For more details, check out our{' '}
                    <a
                        href="https://posthog.com/docs/user-guides/recordings?utm_campaign=session-recording&utm_medium=in-product"
                        target="_blank"
                    >
                        docs
                    </a>
                    .
                </p>
                <SessionRecording />
                <Divider />
                <RestrictedArea Component={AccessControl} minimumAccessLevel={OrganizationMembershipLevel.Admin} />
                <Divider />
                {currentTeam?.access_control && hasAvailableFeature(AvailableFeature.PROJECT_BASED_PERMISSIONING) && (
                    <BindLogic logic={teamMembersLogic} props={{ team: currentTeam }}>
                        <TeamMembers user={user} team={currentTeam} />
                        <Divider />
                    </BindLogic>
                )}
                <RestrictedArea
                    Component={DangerZone}
                    minimumAccessLevel={OrganizationMembershipLevel.Admin}
                    scope={RestrictionScope.Project}
                />
            </Card>
        </div>
    )
}
