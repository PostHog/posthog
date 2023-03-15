import { LemonButton } from '@posthog/lemon-ui'
import { Col, Row } from 'antd'
import { IconPlayCircle } from 'lib/lemon-ui/icons'

export function RecordingsFeatureFlagCard(): JSX.Element {
    return (
        <div className="border rounded p-4">
            <Row justify="space-between" align="middle">
                <Col>
                    <h3>Recordings</h3>5 recordings
                </Col>
                <Col>
                    <LemonButton type="secondary" sideIcon={<IconPlayCircle />}>
                        View Recordings
                    </LemonButton>
                </Col>
            </Row>
        </div>
    )
}
