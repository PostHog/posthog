import React from 'react'
import { useActions, useValues } from 'kea'
import { Col } from 'antd'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { THIRD_PARTY, BOOKMARKLET, platforms } from 'scenes/ingestion/constants'
import { LemonButton } from 'lib/components/LemonButton'
import './Panels.scss'
import { PanelSupport } from './PanelComponents'
import { LemonDivider } from 'lib/components/LemonDivider'

export function PlatformPanel(): JSX.Element {
    const { setPlatform } = useActions(ingestionLogic)
    const { onboardingSidebarEnabled } = useValues(ingestionLogic)

    return (
        <div className="welcome-panel">
            <h1 className="ingestion-title">Welcome to PostHog</h1>
            <p>
                First things first, where do you want to send events from? You can always instrument more sources later.
            </p>
            <LemonDivider thick dashed style={{ marginTop: 24, marginBottom: 24 }} />
            <Col style={{ marginBottom: 16 }}>
                {platforms.map((platform) => (
                    <LemonButton
                        key={platform}
                        fullWidth
                        center
                        size="large"
                        type="primary"
                        className="mb-05"
                        onClick={() => setPlatform(platform)}
                    >
                        {platform}
                    </LemonButton>
                ))}
                <LemonButton
                    onClick={() => setPlatform(THIRD_PARTY)}
                    fullWidth
                    center
                    size="large"
                    className="mb-05"
                    type="primary"
                >
                    {THIRD_PARTY}
                </LemonButton>
                <LemonButton type="secondary" size="large" fullWidth center onClick={() => setPlatform(BOOKMARKLET)}>
                    {BOOKMARKLET}
                </LemonButton>
            </Col>
            {!onboardingSidebarEnabled && <PanelSupport />}
        </div>
    )
}
