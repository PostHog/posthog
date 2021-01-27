import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { hot } from 'react-hot-loader/root'
import { Collapse } from 'antd'

const { Panel } = Collapse

export const OnboardingSetup = hot(_OnboardingSetup)
function _OnboardingSetup(): JSX.Element {
    return (
        <div>
            <PageHeader
                title="Setup"
                caption="Get your PostHog instance up and running with all the bells and whistles"
            />

            <Collapse defaultActiveKey={['1']}>
                <Panel header="This is panel header 1" key="1">
                    <p>text</p>
                </Panel>
                <Panel header="This is panel header 2" key="2">
                    <p>text</p>
                </Panel>
                <Panel header="This is panel header 3" key="3">
                    <p>text</p>
                </Panel>
            </Collapse>
        </div>
    )
}
