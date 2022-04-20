import { Col, Row } from 'antd'
import { useValues, useActions } from 'kea'
import { IconInfo } from 'lib/components/icons'
import { JSBookmarklet } from 'lib/components/JSBookmarklet'
import React from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { CardContainer } from '../CardContainer'
import { ingestionLogic } from '../ingestionLogic'
import './Panels.scss'

export function BookmarkletPanel(): JSX.Element {
    const { index, totalSteps } = useValues(ingestionLogic)
    const { setPlatform, setVerify } = useActions(ingestionLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <CardContainer
            index={index}
            totalSteps={totalSteps}
            nextButton={true}
            onSubmit={() => setVerify(true)}
            onBack={() => setPlatform(null)}
        >
            {currentTeam && (
                <div style={{ padding: 16, paddingTop: 0 }}>
                    <h1 style={{ fontSize: 28, fontWeight: 800, marginBottom: 8 }}>Just exploring?</h1>
                    <h2 style={{ fontSize: 20, fontWeight: 800 }}>
                        Immediately run PostHog on your website for some initial exploring
                    </h2>
                    <p>
                        If you want to quickly test PostHog in your website without changing any code, try out our
                        bookmarklet.
                    </p>
                    <Row gutter={24} className="bookmarklet-warning">
                        <Col span={2} className="warning-icon">
                            <IconInfo style={{ fontSize: '2em', color: 'var(--muted-alt)' }} />
                        </Col>
                        <Col span={22}>
                            <p>
                                Please note this installation is only temporary and intended just for testing. It will
                                only work for the current page and only in your browser session. The bookmarklet is not
                                a permanent form of ingestion.
                            </p>
                        </Col>
                    </Row>
                    <Row>
                        Steps
                        <ul>
                            <li>1. Drag the PostHog Bookmarklet link below to your bookmarks toolbar.</li>
                            <li>2. Open the website you want to track and click on the bookmark you just added.</li>
                            <li>3. Click continue below and see events coming in.</li>
                        </ul>
                    </Row>
                    <Row>
                        <JSBookmarklet team={currentTeam} />
                    </Row>
                </div>
            )}
        </CardContainer>
    )
}
