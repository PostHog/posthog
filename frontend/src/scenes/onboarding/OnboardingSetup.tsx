import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { hot } from 'react-hot-loader/root'
import { Button, Collapse } from 'antd'
import { ProjectOutlined, CodeOutlined, CheckOutlined, CheckCircleOutlined } from '@ant-design/icons'
import './OnboardingSetup.scss'
import { useActions, useValues } from 'kea'
import { onboardingSetupLogic } from './onboardingSetupLogic'
import { CreateProjectModal } from 'scenes/project/CreateProjectModal'
import { Link } from 'lib/components/Link'
import { IconExternalLink } from 'lib/components/icons'

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
    stepNumber,
    icon,
    identifier,
    disabled,
    completed,
    handleClick,
}: {
    label: string
    stepNumber: number
    icon: React.ReactNode
    identifier: string
    disabled?: boolean
    completed?: boolean
    handleClick?: () => void
}): JSX.Element {
    return (
        <div
            className={`onboarding-step${disabled ? ' disabled' : ''}${completed ? ' completed' : ''}`}
            onClick={() => !disabled && !completed && handleClick && handleClick()}
            data-attr="onboarding-setup-step"
            data-step={identifier}
        >
            <div className="step-number">Step {stepNumber}</div>
            <div className="icon-container">{icon}</div>
            {completed ? (
                <div className="completed-label">
                    <CheckCircleOutlined />
                    {label}
                </div>
            ) : (
                <Button type="primary" disabled={disabled}>
                    {label}
                </Button>
            )}
        </div>
    )
}

export const OnboardingSetup = hot(_OnboardingSetup)
function _OnboardingSetup(): JSX.Element {
    const { stepProjectSetup, stepInstallation, projectModalShown, stepVerification, defaultActiveSection } = useValues(
        onboardingSetupLogic
    )
    const { switchToNonDemoProject, setProjectModalShown } = useActions(onboardingSetupLogic)

    return (
        <div className="onboarding-setup">
            <PageHeader
                title="Setup"
                caption="Get your PostHog instance up and running with all the bells and whistles"
            />

            <Collapse defaultActiveKey={defaultActiveSection} expandIconPosition="right" accordion>
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
                            stepNumber={1}
                            identifier="set-up-project"
                            completed={stepProjectSetup}
                            handleClick={() => setProjectModalShown(true)}
                        />
                        <OnboardingStep
                            label="Install PostHog"
                            icon={<CodeOutlined />}
                            stepNumber={2}
                            identifier="install-posthog"
                            disabled={!stepProjectSetup}
                            completed={stepInstallation}
                            handleClick={() => switchToNonDemoProject('/ingestion')}
                        />
                        <OnboardingStep
                            label="Verify your events"
                            icon={<CheckOutlined />}
                            stepNumber={3}
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
                    collapsible={defaultActiveSection < 2 ? 'disabled' : undefined}
                >
                    <p>text</p>
                </Panel>
                <Panel
                    header={
                        <PanelHeader
                            title="First steps"
                            caption={
                                <>
                                    Walk through some initial steps (like creating your first action). Optional, but you
                                    get <b>extra free event allocation for every month, forever</b>.
                                </>
                            }
                            stepNumber={3}
                        />
                    }
                    key="3"
                    collapsible="disabled"
                >
                    <p>text</p>
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
                            It’s helpful to separate your different apps in multiple projects. Read more about our
                            recommendations and{' '}
                            <Link
                                to="https://posthog.com/docs/features/organizations?utm_medium=in-product&utm_campaign=onboarding-setup-2822"
                                rel="noopener"
                                target="_blank"
                            >
                                best practices <IconExternalLink />
                            </Link>
                        </div>
                    </div>
                }
            />
        </div>
    )
}
