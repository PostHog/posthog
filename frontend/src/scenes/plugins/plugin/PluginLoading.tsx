import { Card, Col, Row, Skeleton } from 'antd'

export function PluginLoading(): JSX.Element {
    return (
        <>
            {[1, 2, 3].map((i) => (
                <Col key={i} style={{ marginBottom: 20, width: '100%' }} className="plugins-scene-plugin-card-col">
                    <Card className="plugins-scene-plugin-card">
                        <Row align="middle" className="plugin-card-row">
                            <Col className="hide-plugin-image-below-500">
                                <Skeleton.Avatar active size="large" shape="square" />
                            </Col>
                            <Col style={{ flex: 1 }}>
                                <Skeleton title={false} paragraph={{ rows: 2 }} active />
                            </Col>
                            <Col>
                                <span className="show-over-500">
                                    <Skeleton.Button style={{ width: 100 }} />
                                </span>
                                <span className="hide-over-500">
                                    <Skeleton.Button style={{ width: 32 }} />
                                </span>
                            </Col>
                        </Row>
                    </Card>
                </Col>
            ))}
        </>
    )
}
