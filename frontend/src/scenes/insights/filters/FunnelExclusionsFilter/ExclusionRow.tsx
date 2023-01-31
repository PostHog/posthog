import { Col, Row } from 'antd'

export function ExclusionRow({
    seriesIndicator,
    filter,
    suffix,
    isVertical,
}: {
    seriesIndicator?: JSX.Element | string
    suffix?: JSX.Element | string
    filter?: JSX.Element | string
    isVertical?: boolean
}): JSX.Element {
    return (
        <Row wrap={false} align={isVertical ? 'top' : 'middle'} style={{ width: '100%' }}>
            <Col style={{ padding: `${isVertical ? 5 : 0}px 8px` }}>{seriesIndicator}</Col>
            <Col flex="auto">
                <Row align="middle" wrap={isVertical}>
                    {filter}
                    {suffix}
                </Row>
            </Col>
        </Row>
    )
}
