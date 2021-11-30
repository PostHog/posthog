import { Col, Row } from 'antd'
import clsx from 'clsx'
import React from 'react'
import './SkeletonGraph.scss'

interface SkeletonGraphProps {
    isLoading?: boolean
}

export function SkeletonGraph({ isLoading }: SkeletonGraphProps): JSX.Element {
    // https://xkcd.com/221/
    const provenRandom = [57, 88, 6, 0, 27, 33, 44, 100, 4, 23, 57, 9, 45, 30, 33, 28, 23, 18, 83, 98, 93, 0, 12]

    return (
        <Row justify="space-between" align="stretch" className={'skeleton-graph'}>
            <Col span={1} className={'left-axis'} />
            {provenRandom.map((n, index) => {
                return (
                    <Col span={1} key={index} style={{ display: 'flex', alignItems: 'flex-end' }}>
                        <div
                            className={clsx(['skeleton-bar', { 'is-loading': isLoading }])}
                            style={{ height: `${n}%` }}
                        />
                    </Col>
                )
            })}
        </Row>
    )
}
