import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { hot } from 'react-hot-loader/root'
import { Collapse } from 'antd'
import './OnboardingSetup.scss'

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

export const OnboardingSetup = hot(_OnboardingSetup)
function _OnboardingSetup(): JSX.Element {
    return (
        <div className="onboarding-setup">
            <PageHeader
                title="Setup"
                caption="Get your PostHog instance up and running with all the bells and whistles"
            />

            <Collapse defaultActiveKey={['1']} expandIconPosition="right">
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
                    <p>text</p>
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
                    disabled
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
                    disabled
                >
                    <p>text</p>
                </Panel>
            </Collapse>
        </div>
    )
}
