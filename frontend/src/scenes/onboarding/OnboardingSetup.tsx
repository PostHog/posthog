import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { Button, Col, Collapse, Progress, Row, Space, Switch } from 'antd'
import {
    ProjectOutlined,
    CodeOutlined,
    CheckOutlined,
    CheckCircleOutlined,
    PlaySquareOutlined,
    SlackOutlined,
    UsergroupAddOutlined,
    PlusOutlined,
    ArrowRightOutlined,
    ApiOutlined,
} from '@ant-design/icons'
import './OnboardingSetup.scss'
import { useActions, useValues } from 'kea'
import { onboardingSetupLogic } from './onboardingSetupLogic'
import { CreateProjectModal } from 'scenes/project/CreateProjectModal'
import { Link } from 'lib/components/Link'
import { IconExternalLink } from 'lib/components/icons'
import { BulkInviteModal } from 'scenes/organization/Settings/BulkInviteModal'
import { LinkButton } from 'lib/components/LinkButton'
import { organizationLogic } from 'scenes/organizationLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { pluginsLogic } from '../plugins/pluginsLogic'
import { PluginImage } from '../plugins/plugin/PluginImage'
import { endWithPunctation, Loading } from '../../lib/utils'
import { preflightLogic } from '../PreflightCheck/logic'

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
        <div className="panel-title" data-attr={`setup-header-${stepNumber}`}>
            <div className="step-number">{stepNumber}</div>
            <div>
                <h3 className="l3">{title}</h3>
                <div className="caption">{caption}</div>
            </div>
        </div>
    )
}

interface OnboardingStepContentsProps {
    label?: string
    icon: React.ReactNode
    completed?: boolean
    disabled?: boolean
    caption?: JSX.Element | string
    actionElement?: JSX.Element
    identifier: string
    handleClick?: () => void
    analyticsExtraArgs?: Record<string, string | number | boolean>
}

function OnboardingStepContents({
    icon,
    label,
    completed,
    caption,
    disabled,
    actionElement,
    identifier,
    handleClick,
    analyticsExtraArgs = {},
}: OnboardingStepContentsProps): JSX.Element {
    const { reportOnboardingStepTriggered } = useActions(eventUsageLogic)

    const onClick = (): void => {
        if (disabled || completed || !handleClick) {
            return
        }
        reportOnboardingStepTriggered(identifier, analyticsExtraArgs)
        handleClick()
    }

    actionElement = (
        <>
            {actionElement || (
                <Button type="primary" disabled={disabled}>
                    {label}
                </Button>
            )}
        </>
    )
    return (
        <div className="onboarding-step-contents" onClick={onClick} data-step={identifier}>
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

interface OnboardingStepProps {
    title?: string
    completed?: boolean
    disabled?: boolean
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
    actionElement,
    analyticsExtraArgs = {},
}: OnboardingStepProps & OnboardingStepContentsProps): JSX.Element {
    return (
        <div
            className={`onboarding-step${disabled ? ' disabled' : ''}${completed ? ' completed' : ''}`}
            data-attr="onboarding-setup-step"
        >
            {title && <div className="title">{title}</div>}
            <OnboardingStepContents
                label={label}
                icon={icon}
                completed={completed}
                caption={caption}
                disabled={disabled}
                actionElement={actionElement}
                handleClick={handleClick}
                analyticsExtraArgs={analyticsExtraArgs}
                identifier={identifier}
            />
        </div>
    )
}

function OnboardingStepGroup({
    title,
    disabled,
    completed,
    entries,
}: OnboardingStepProps & { entries: OnboardingStepContentsProps[] }): JSX.Element {
    return (
        <div
            className={`onboarding-step${disabled ? ' disabled' : ''}${completed ? ' completed' : ''}`}
            data-attr="onboarding-setup-step"
        >
            {title && <div className="title">{title}</div>}
            <Row>
                {entries.map(
                    (
                        {
                            label,
                            icon,
                            completed,
                            disabled,
                            caption,
                            actionElement,
                            handleClick,
                            identifier,
                            analyticsExtraArgs,
                        },
                        index
                    ) => (
                        <OnboardingStepContents
                            key={`identifier-${index}`}
                            label={label}
                            icon={icon}
                            completed={completed}
                            caption={caption}
                            disabled={disabled}
                            actionElement={actionElement}
                            handleClick={handleClick}
                            identifier={identifier}
                            analyticsExtraArgs={analyticsExtraArgs}
                        />
                    )
                )}
            </Row>
        </div>
    )
}

export function OnboardingSetup(): JSX.Element {
    const {
        stepProjectSetup,
        stepInstallation,
        projectModalShown,
        stepVerification,
        currentSection,
        inviteTeamModalShown,
        teamInviteAvailable,
        progressPercentage,
        slackCalled,
    } = useValues(onboardingSetupLogic)
    const {
        switchToNonDemoProject,
        setProjectModalShown,
        setInviteTeamModalShown,
        completeOnboarding,
        callSlack,
    } = useActions(onboardingSetupLogic)

    const { installedPlugins, pluginsLoading, pluginConfigsLoading } = useValues(pluginsLogic)
    const { toggleEnabled } = useActions(pluginsLogic)

    const { preflight } = useValues(preflightLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentOrganizationLoading } = useValues(organizationLogic)

    const UTM_TAGS = 'utm_medium=in-product&utm_campaign=onboarding-setup-2822'

    if (currentOrganizationLoading) {
        return <Loading />
    }

    return (
        <div className="onboarding-setup">
            {currentSection ? (
                <>
                    <Row gutter={16}>
                        <Col span={18}>
                            <PageHeader
                                title="Setup"
                                caption="Get your PostHog instance up and running with all the bells and whistles"
                            />
                        </Col>
                        <Col span={6} style={{ display: 'flex', alignItems: 'center' }}>
                            <Progress percent={progressPercentage} strokeColor="var(--purple)" strokeWidth={16} />
                        </Col>
                    </Row>

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
                            <Space direction="vertical" align="center" className="steps-space">
                                <Row>
                                    <OnboardingStep
                                        title="Enable session recording"
                                        icon={<PlaySquareOutlined />}
                                        identifier="session-recording"
                                        handleClick={() =>
                                            updateCurrentTeam({
                                                session_recording_opt_in: !currentTeam?.session_recording_opt_in,
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
                                        actionElement={
                                            <div style={{ fontWeight: 'bold' }}>
                                                {currentTeam?.session_recording_opt_in ? (
                                                    <span style={{ color: 'var(--success)' }}>Enabled</span>
                                                ) : (
                                                    <span style={{ color: 'var(--danger)' }}>Disabled</span>
                                                )}
                                                <Switch
                                                    checked={currentTeam?.session_recording_opt_in}
                                                    loading={currentTeamLoading}
                                                    style={{ marginLeft: 6 }}
                                                />
                                            </div>
                                        }
                                        analyticsExtraArgs={{
                                            new_session_recording_enabled: !currentTeam?.session_recording_opt_in,
                                        }}
                                    />
                                    <OnboardingStep
                                        title="Join us on Slack"
                                        icon={<SlackOutlined />}
                                        identifier="slack"
                                        handleClick={() => {
                                            callSlack()
                                            window.open(`https://posthog.com/slack?s=app&${UTM_TAGS}`, '_blank')
                                        }}
                                        caption="Fastest way to reach the PostHog team and the community."
                                        actionElement={
                                            <Button type={slackCalled ? 'default' : 'primary'} icon={<SlackOutlined />}>
                                                Join us
                                            </Button>
                                        }
                                    />
                                    {teamInviteAvailable && (
                                        <OnboardingStep
                                            title="Invite your team members"
                                            icon={<UsergroupAddOutlined />}
                                            identifier="invite-team"
                                            handleClick={() => setInviteTeamModalShown(true)}
                                            caption="Spread the knowledge, share insights with everyone in your team."
                                            actionElement={
                                                <Button type="primary" icon={<PlusOutlined />}>
                                                    Invite my team
                                                </Button>
                                            }
                                        />
                                    )}
                                </Row>
                                <Row>
                                    <OnboardingStepGroup
                                        title="Configure plugins"
                                        entries={installedPlugins
                                            .map(({ name, description, url, plugin_type, pluginConfig }) => ({
                                                identifier: `plugins-${name}`,
                                                icon: <PluginImage size="small" pluginType={plugin_type} url={url} />,
                                                caption: (
                                                    <>
                                                        <b>{name}</b>
                                                        <br />
                                                        {endWithPunctation(description)}
                                                    </>
                                                ),
                                                actionElement: (
                                                    <div style={{ fontWeight: 'bold' }}>
                                                        {pluginConfig.enabled ? (
                                                            <span style={{ color: 'var(--success)' }}>Enabled</span>
                                                        ) : (
                                                            <span style={{ color: 'var(--danger)' }}>Disabled</span>
                                                        )}
                                                        <Switch
                                                            checked={pluginConfig.enabled}
                                                            loading={pluginsLoading || pluginConfigsLoading}
                                                            style={{ marginLeft: 6 }}
                                                        />
                                                    </div>
                                                ),
                                                handleClick: () =>
                                                    toggleEnabled({
                                                        id: pluginConfig.id,
                                                        enabled: !pluginConfig.enabled,
                                                    }),
                                            }))
                                            .concat([
                                                {
                                                    identifier: 'plugins-more',
                                                    icon: <ApiOutlined />,
                                                    caption: (
                                                        <>
                                                            <b>More…</b>
                                                            <br />
                                                            {preflight?.cloud
                                                                ? 'See other verified plugins.'
                                                                : 'Install other verified or external plugins. Or even write your own.'}
                                                        </>
                                                    ),
                                                    actionElement: (
                                                        <Button type="primary" icon={<ApiOutlined />}>
                                                            Open Plugins page
                                                        </Button>
                                                    ),
                                                    handleClick: () => window.open(`/project/plugins`, '_blank'),
                                                },
                                            ])}
                                    />
                                </Row>
                                <Row align="middle" style={{ margin: '1rem 0' }}>
                                    <Button
                                        type="default"
                                        onClick={completeOnboarding}
                                        loading={currentOrganizationLoading}
                                        data-attr="onboarding-setup-complete"
                                        icon={<CheckOutlined />}
                                    >
                                        Finish setup
                                    </Button>
                                </Row>
                            </Space>
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
                    <BulkInviteModal visible={inviteTeamModalShown} onClose={() => setInviteTeamModalShown(false)} />
                </>
            ) : (
                <div className="already-completed">
                    <CheckCircleOutlined className="completed-icon" />{' '}
                    <h2 className="">Your organization is set up!</h2>
                    <div className="text-muted">
                        Looks like your organization is good to go. If you still need some help, check out{' '}
                        <Link
                            to={`https://posthog.com/docs?${UTM_TAGS}&utm_message=onboarding-completed`}
                            target="_blank"
                            rel="noopener"
                        >
                            our docs <IconExternalLink />
                        </Link>
                    </div>
                    <div style={{ marginTop: 32 }}>
                        <LinkButton type="primary" to="/" data-attr="onbording-completed-insights">
                            Go to insights <ArrowRightOutlined />
                        </LinkButton>
                    </div>
                </div>
            )}
        </div>
    )
}
