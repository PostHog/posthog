import { Col } from 'antd'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import React from 'react'
import { BOOKMARKLET } from '../constants'
import { ingestionLogic } from '../ingestionLogic'
import './Panels.scss'

export function PanelFooter(): JSX.Element {
    const { platform } = useValues(ingestionLogic)
    const { setPlatform, setVerify } = useActions(ingestionLogic)

    return (
        <Col className="panel-footer">
            {platform === BOOKMARKLET ? (
                <div>
                    <LemonButton
                        type="primary"
                        fullWidth
                        center
                        className="ingestion-btn"
                        onClick={() => setVerify(true)}
                    >
                        Try PostHog with the exploration bookmarklet
                    </LemonButton>
                    <LemonButton
                        fullWidth
                        center
                        type="secondary"
                        className="ingestion-btn inverted"
                        onClick={() => setPlatform(null)}
                    >
                        Back to setup
                    </LemonButton>
                </div>
            ) : (
                <div>
                    <LemonButton
                        type="primary"
                        fullWidth
                        center
                        className="ingestion-btn"
                        onClick={() => setVerify(true)}
                    >
                        Continue
                    </LemonButton>
                    <LemonButton
                        fullWidth
                        center
                        type="secondary"
                        className="ingestion-btn inverted"
                        onClick={() => setVerify(true)}
                    >
                        Skip for now
                    </LemonButton>
                </div>
            )}
            <p className="text-center mb-0">
                Need help? <a>Visit support</a> or <a>read our documentation</a>
            </p>
        </Col>
    )
}
