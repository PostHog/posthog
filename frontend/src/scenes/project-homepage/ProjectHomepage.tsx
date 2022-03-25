import React from 'react'
import './ProjectHomepage.scss'
import { PageHeader } from 'lib/components/PageHeader'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { DashboardPlacement, SessionRecordingType } from '~/types'
import { Button, Row, Skeleton, Typography } from 'antd'
import { PlayCircleOutlined } from '@ant-design/icons'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { LemonSpacer } from 'lib/components/LemonRow'
import { PrimaryDashboardModal } from './PrimaryDashboardModal'
import { primaryDashboardModalLogic } from './primaryDashboardModalLogic'
import { HomeIcon } from 'lib/components/icons'
import { projectHomepageLogic } from 'scenes/project-homepage/projectHomepageLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { asDisplay } from 'scenes/persons/PersonHeader'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { humanFriendlyDuration } from 'lib/utils'
import { LemonButton } from 'lib/components/LemonButton'
import { dayjs } from 'lib/dayjs'
import { SessionPlayerDrawer } from 'scenes/session-recordings/SessionPlayerDrawer'

interface RecordingRowProps {
    recording: SessionRecordingType
}

function RecordingRow({ recording }: RecordingRowProps): JSX.Element {
    const { openRecordingModal } = useActions(projectHomepageLogic)
    return (
        <LemonButton
            fullWidth
            className="recording-row"
            onClick={() => {
                openRecordingModal(recording.id)
            }}
        >
            <ProfilePicture name={asDisplay(recording.person)} />
            <div className="recording-person-text-container" style={{ flexDirection: 'column', display: 'flex' }}>
                <p className="recording-person-text">{asDisplay(recording.person)}</p>
                <p className="text-muted recording-start-time">{dayjs(recording.start_time).fromNow()}</p>
            </div>
            <span className="text-muted recording-duration">{humanFriendlyDuration(recording.recording_duration)}</span>
            <PlayCircleOutlined size={24} />
        </LemonButton>
    )
}

export function ProjectHomepage(): JSX.Element {
    const { dashboardLogic, recordings, recordingsLoading, sessionRecordingId } = useValues(projectHomepageLogic)
    const { closeRecordingModal } = useActions(projectHomepageLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)
    const { dashboard } = useValues(dashboardLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { showPrimaryDashboardModal } = useActions(primaryDashboardModalLogic)

    const headerButtons = (
        <div style={{ display: 'flex' }}>
            <Button
                data-attr="project-home-invite-team-members"
                onClick={() => {
                    showInviteModal()
                }}
                className="mr-05"
            >
                Invite members
            </Button>
            <Button
                data-attr="project-home-new-insight"
                onClick={() => {
                    router.actions.push(urls.insightNew())
                }}
            >
                New insight
            </Button>
        </div>
    )

    return (
        <div className="project-homepage">
            {!!sessionRecordingId && <SessionPlayerDrawer onClose={closeRecordingModal} />}

            <PageHeader title={currentTeam?.name || ''} delimited buttons={headerButtons} />
            {featureFlags[FEATURE_FLAGS.HOMEPAGE_LISTS] && (
                <div className="top-list-container-horizontal">
                    <div className="top-list">
                        <CompactList
                            title="New Recordings"
                            viewAllURL={urls.sessionRecordings()}
                            loading={recordingsLoading}
                            emptyMessage={
                                currentTeam?.session_recording_opt_in
                                    ? {
                                          title: 'There are no recordings for this project',
                                          description:
                                              'Make sure you have the javascript snippet setup in your website.',
                                          buttonText: 'Learn more',
                                          buttonHref: 'https://posthog.com/docs/user-guides/recordings',
                                      }
                                    : {
                                          title: 'Recordings are not enabled for this project',
                                          description: 'Once recordings are enabled, new recordings will display here.',
                                          buttonText: 'Enable recordings',
                                          buttonTo: urls.projectSettings() + '#recordings',
                                      }
                            }
                            items={recordings}
                            renderRow={(recording: SessionRecordingType, index) => (
                                <RecordingRow key={index} recording={recording} />
                            )}
                        />
                    </div>
                    <div className="spacer" />
                </div>
            )}
            {currentTeam?.primary_dashboard ? (
                <div>
                    <div>
                        <Row className="homepage-dashboard-header">
                            <div className="dashboard-title-container">
                                {!dashboard && <Skeleton active paragraph={false} />}
                                {dashboard?.name && (
                                    <>
                                        <HomeIcon className="mr-05" style={{ width: 18, height: 18 }} />
                                        <Typography.Title className="dashboard-name" level={4}>
                                            {dashboard?.name}
                                        </Typography.Title>
                                    </>
                                )}
                            </div>
                            <Button data-attr="project-home-new-insight" onClick={showPrimaryDashboardModal}>
                                Change dashboard
                            </Button>
                        </Row>
                        <LemonSpacer large />
                    </div>
                    <Dashboard
                        id={currentTeam.primary_dashboard.toString()}
                        placement={DashboardPlacement.ProjectHomepage}
                    />
                </div>
            ) : (
                <div className="empty-state-container">
                    <HomeIcon className="mb" />
                    <h1>There isn’t a default dashboard set for this project</h1>
                    <p className="mb">
                        Default dashboards are shown to everyone in the project. When you set a default, it’ll show up
                        here.
                    </p>
                    <Button
                        type="primary"
                        data-attr="project-home-new-insight"
                        onClick={() => {
                            showPrimaryDashboardModal()
                        }}
                    >
                        Select a default dashboard
                    </Button>
                </div>
            )}
            <PrimaryDashboardModal />
        </div>
    )
}

export const scene: SceneExport = {
    component: ProjectHomepage,
    logic: projectHomepageLogic,
}
