import React, { useState, useEffect } from 'react'
import './PayCard.scss'
import { ArrowRightOutlined, CloseOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Col, Row } from 'antd'
import { AvailableFeature } from '~/types'
import { router } from 'kea-router'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { UPGRADE_LINK } from 'lib/constants'

interface PayCardProps {
    title: string
    caption: string
    docsLink?: string
    identifier: AvailableFeature
    dismissable?: boolean
}

export function PayCard({
    title,
    caption,
    docsLink,
    identifier,
    dismissable = true,
}: PayCardProps): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { push } = useActions(router)
    const [shown, setShown] = useState(false)
    const storageKey = `pay-gate-dismissed-${identifier}`
    const { reportPayGateDismissed, reportPayGateShown } = useActions(eventUsageLogic)

    const handleClick = (): void => {
        const link = UPGRADE_LINK(preflight?.cloud)
        if (link.target) {
            window.open(link.url, link.target)
        } else {
            push(link.url)
        }
    }

    const close = (e: React.MouseEvent): void => {
        // TODO
        e.stopPropagation()
        setShown(false)
        window.localStorage.setItem(storageKey, '1')
        reportPayGateDismissed(identifier)
    }

    useEffect(() => {
        if (!dismissable || !window.localStorage.getItem(storageKey)) {
            setShown(true)
            reportPayGateShown(identifier)
        }
    }, [dismissable])

    if (!shown) {
        return null
    }

    return (
        <div className="pay-card">
            {dismissable && (
                <div className="close-button" onClick={close}>
                    <CloseOutlined />
                </div>
            )}
            <Row onClick={handleClick}>
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
                                    Learn more
                                </a>
                            </>
                        )}
                    </p>
                    {preflight?.cloud ? (
                        <p>
                            Click to <b>set up your billing details and gain access to these features.</b>
                        </p>
                    ) : (
                        <p>
                            Click to <b>explore license options.</b>
                        </p>
                    )}
                </Col>
                <Col span={1} style={{ display: 'flex', alignItems: 'center' }}>
                    <ArrowRightOutlined style={{ color: 'var(--muted-alt)', fontSize: '1.2em' }} />
                </Col>
            </Row>
        </div>
    )
}
