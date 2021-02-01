import { PageHeader } from 'lib/components/PageHeader'
import React, { useState } from 'react'
import { hot } from 'react-hot-loader/root'
import { Button, Collapse, Switch } from 'antd'
import {
    ProjectOutlined,
    CodeOutlined,
    CheckOutlined,
    CheckCircleOutlined,
    PlaySquareOutlined,
    SlackOutlined,
    UsergroupAddOutlined,
    PlusOutlined,
} from '@ant-design/icons'
import './OnboardingSetup.scss'
import { useActions, useValues } from 'kea'
import { onboardingSetupLogic } from './onboardingSetupLogic'
import { CreateProjectModal } from 'scenes/project/CreateProjectModal'
import { Link } from 'lib/components/Link'
import { IconExternalLink } from 'lib/components/icons'
import { userLogic } from 'scenes/userLogic'

const { Panel } = Collapse

function PanelHeader({
    title,
    caption,
    stepNumber,
}: {
    title: string
    caption: string | JSX.Element
    stepNumber: number
}): JSX.Element {
    return (
        <div className="panel-title">
            <div className="step-number">{stepNumber}</div>
            <div>
                <h3 className="l3">{title}</h3>
                <div className="caption">{caption}</div>
            </div>
        </div>
    )
}

function OnboardingStep({
    label,
    title,
    icon,
    identifier,
    disabled,
    completed,
    handleClick,
    caption,
    customActionElement,
}: {
    label?: string
    title?: string
    icon: React.ReactNode
    identifier: string
    disabled?: boolean
    completed?: boolean
    handleClick?: () => void
    caption?: JSX.Element | string
    customActionElement?: JSX.Element
}): JSX.Element {
    const actionElement = (
        <>
            {customActionElement || (
                <Button type="primary" disabled={disabled}>
                    {label}
                </Button>
            )}
        </>
    )

    return (
        <div
            className={`onboarding-step${disabled ? ' disabled' : ''}${completed ? ' completed' : ''}`}
            onClick={() => !disabled && !completed && handleClick && handleClick()}
            data-attr="onboarding-setup-step"
            data-step={identifier}
        >
            {title && <div className="title">{title}</div>}
            <div className="icon-container">{icon}</div>
            {caption && <div className="caption">{caption}</div>}
            {completed ? (
                <div className="completed-label">
                    <CheckCircleOutlined />
                    {label}
                </div>
            ) : (
                actionElement
            )}
        </div>
    )
}

export const OnboardingSetup = hot(_OnboardingSetup)
function _OnboardingSetup(): JSX.Element {
    const [slackClicked, setslackClicked] = useState(false)
    const { stepProjectSetup, stepInstallation, projectModalShown, stepVerification, currentSection } = useValues(
        onboardingSetupLogic
    )
    const { user, userUpdateLoading } = useValues(userLogic)
    const { userUpdateRequest } = useActions(userLogic)

    const { switchToNonDemoProject, setProjectModalShown } = useActions(onboardingSetupLogic)

    const UTM_TAGS = 'utm_medium=in-product&utm_campaign=onboarding-setup-2822'

    return (
        <div className="onboarding-setup">
            {currentSection ? (
                <>
                    <PageHeader
                        title="Setup"
                        caption="Get your PostHog instance up and running with all the bells and whistles"
                    />

                    <Collapse defaultActiveKey={currentSection} expandIconPosition="right" accordion>
                        <Panel
                            header={
                                <PanelHeader
                                    title="Event Ingestion"
                                    caption="First things first, you need to connect PostHog to your website. You’ll be able to add more sources later."
                                    stepNumber={1}
                                />
                            }
                            key="1"
                        >
                            <div className="step-list">
                                <OnboardingStep
                                    label="Set up project"
                                    icon={<ProjectOutlined />}
                                    title="Step 1"
                                    identifier="set-up-project"
                                    completed={stepProjectSetup}
                                    handleClick={() => setProjectModalShown(true)}
                                />
                                <OnboardingStep
                                    label="Install PostHog"
                                    icon={<CodeOutlined />}
                                    title="Step 2"
                                    identifier="install-posthog"
                                    disabled={!stepProjectSetup}
                                    completed={stepInstallation}
                                    handleClick={() => switchToNonDemoProject('/ingestion')}
                                />
                                <OnboardingStep
                                    label="Verify your events"
                                    icon={<CheckOutlined />}
                                    title="Step 3"
                                    identifier="verify-events"
                                    disabled={!stepProjectSetup || !stepInstallation}
                                    completed={stepVerification}
                                    handleClick={() => switchToNonDemoProject('/ingestion/verify')}
                                />
                            </div>
                        </Panel>
                        <Panel
                            header={
                                <PanelHeader
                                    title="Configuration"
                                    caption="Tune the settings of PostHog to make sure it works best for you and your team."
                                    stepNumber={2}
                                />
                            }
                            key="2"
                            collapsible={currentSection < 2 ? 'disabled' : undefined}
                        >
                            <div className="step-list">
                                <OnboardingStep
                                    title="Enable session recording"
                                    icon={<PlaySquareOutlined />}
                                    identifier="session-recording"
                                    handleClick={() =>
                                        userUpdateRequest({
                                            team: { session_recording_opt_in: !user?.team?.session_recording_opt_in },
                                        })
                                    }
                                    caption={
                                        <>
                                            Play user interactions as if you were right there with them.{' '}
                                            <Link
                                                to={`https://posthog.com/docs/features/session-recording?${UTM_TAGS}`}
                                                rel="noopener"
                                                target="_blank"
                                            >
                                                Learn more
                                            </Link>
                                            .
                                        </>
                                    }
                                    customActionElement={
                                        <div style={{ fontWeight: 'bold' }}>
                                            {user?.team?.session_recording_opt_in ? (
                                                <span style={{ color: 'var(--success)' }}>Enabled</span>
                                            ) : (
                                                <span style={{ color: 'var(--danger)' }}>Disabled</span>
                                            )}
                                            <Switch
                                                checked={user?.team?.session_recording_opt_in}
                                                loading={userUpdateLoading}
                                                style={{ marginLeft: 6 }}
                                            />
                                        </div>
                                    }
                                />
                                <OnboardingStep
                                    title="Join us on Slack"
                                    icon={<SlackOutlined />}
                                    identifier="slack"
                                    handleClick={() => {
                                        setslackClicked(true)
                                        window.open(`https://posthog.com/slack?s=app&${UTM_TAGS}`, '_blank')
                                    }}
                                    caption="Fastest way to reach the PostHog team and the community."
                                    customActionElement={
                                        <Button type={slackClicked ? 'default' : 'primary'} icon={<SlackOutlined />}>
                                            Join us
                                        </Button>
                                    }
                                />
                                <OnboardingStep
                                    title="Invite your team members"
                                    icon={<UsergroupAddOutlined />}
                                    identifier="invite-team"
                                    handleClick={() => setProjectModalShown(true)}
                                    caption="Spread the knowledge, share insights with everyone in your team."
                                    customActionElement={
                                        <Button type="primary" icon={<PlusOutlined />}>
                                            Invite my team
                                        </Button>
                                    }
                                />
                            </div>
                            <div className="text-center" style={{ marginTop: 32 }}>
                                <Button type="default">Finish setup</Button>
                            </div>
                        </Panel>
                    </Collapse>
                    <CreateProjectModal
                        isVisible={projectModalShown}
                        setIsVisible={setProjectModalShown}
                        title="Set up your first project"
                        caption={
                            <div className="mb">
                                <div>
                                    Enter a <b>name</b> for your first project
                                </div>
                                <div className="text-muted">
                                    It’s helpful to separate your different apps in multiple projects. Read more about
                                    our recommendations and{' '}
                                    <Link
                                        to={`https://posthog.com/docs/features/organizations?${UTM_TAGS}`}
                                        rel="noopener"
                                        target="_blank"
                                    >
                                        best practices <IconExternalLink />
                                    </Link>
                                </div>
                            </div>
                        }
                    />
                </>
            ) : (
                <div className="already-completed">
                    <CheckCircleOutlined /> <h2 className="">Your organization is already set up!</h2>
                    <div className="text-muted">
                        Looks like your organization is already good to go. If you still need some help, check out{' '}
                        <Link to={`https://posthog.com/docs?${UTM_TAGS}`} target="_blank" rel="noopener">
                            our docs <IconExternalLink />
                        </Link>
                    </div>
                </div>
            )}
        </div>
    )
}
