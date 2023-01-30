import { Col, Row } from 'antd'
import { useValues } from 'kea'
import { IconInfo } from 'lib/components/icons'
import { JSBookmarklet } from 'lib/components/JSBookmarklet'
import { teamLogic } from 'scenes/teamLogic'
import './Panels.scss'
import { PanelFooterToRecordingStep } from 'scenes/ingestion/v1/panels/PanelComponents'

export function BookmarkletPanel(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <div style={{ maxWidth: 800 }}>
            {currentTeam && (
                <div style={{ padding: '0px 16px' }}>
                    <h1 className="ingestion-title mb-2">Just exploring?</h1>
                    <h2 style={{ fontSize: 20, fontWeight: 800 }}>
                        Immediately run PostHog on your website for some initial exploring
                    </h2>
                    <p>
                        If you want to quickly test PostHog in your website without changing any code, try out our
                        bookmarklet.
                    </p>
                    <Row gutter={24} style={{ marginLeft: 0, marginRight: 0 }} className="bookmarklet-warning">
                        <Col span={2} className="warning-icon">
                            <IconInfo style={{ fontSize: '2em', color: 'var(--muted-alt)' }} />
                        </Col>
                        <Col span={22}>
                            <p className="text-muted font-medium">
                                Please note this installation is only temporary and intended just for testing. It will
                                only work for the current page and only in your browser session. The bookmarklet is not
                                a permanent form of ingestion.
                            </p>
                        </Col>
                    </Row>
                    <Row className="bookmarklet-steps">
                        <Col>
                            <h3 className="font-light">Steps</h3>
                            <ol style={{ paddingLeft: 18 }}>
                                <li>Drag the PostHog Bookmarklet link below to your bookmarks toolbar.</li>
                                <li>Open the website you want to track and click on the bookmark you just added.</li>
                                <li>Click continue below and see events coming in.</li>
                            </ol>
                        </Col>
                    </Row>
                    <Row justify="center">
                        <JSBookmarklet team={currentTeam} />
                    </Row>
                </div>
            )}
            <PanelFooterToRecordingStep />
        </div>
    )
}
