import React from 'react'
import './PayCard.scss'
import { ArrowRightOutlined, RightOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { Col, Row } from 'antd'
import { AvailableFeature } from '~/types'
import { router } from 'kea-router'

interface PayCardProps {
    title: string
    caption: string
    docsLink?: string
    identifier: AvailableFeature
}

export function PayCard({ title, caption, docsLink, identifier }: PayCardProps): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { push } = useActions(router)

    const handleClick = (): void => {
        if (preflight?.cloud) {
            push('/organization/billing')
        } else {
            window.open('https://posthog.com/pricing', '_blank')
        }
    }
    return (
        <div className="pay-card" onClick={handleClick}>
            <Row>
                <Col span={23}>
                    <h3>{title}</h3>
                    <p>
                        {caption}
                        {docsLink && (
                            <>
                                {' '}
                                <a
                                    href={`${docsLink}?utm_medium=in-product&utm_campaign=${identifier}`}
                                    target="_blank"
                                    rel="noopener"
                                    onClick={(e) => e.stopPropagation()}
                                >
                                    Learn more <ArrowRightOutlined />
                                </a>
                            </>
                        )}
                    </p>
                    {preflight?.cloud ? (
                        <p>
                            Click here to <b>set up your billing details and gain access to these features.</b>
                        </p>
                    ) : (
                        <p>
                            Click here to <b>explore license options.</b>
                        </p>
                    )}
                </Col>
                <Col span={1} style={{ display: 'flex', fontSize: '2em', alignItems: 'center' }}>
                    <RightOutlined />
                </Col>
            </Row>
        </div>
    )
}
