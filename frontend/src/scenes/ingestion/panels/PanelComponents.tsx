import { Col, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { IconChevronRight } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonDivider } from 'lib/components/LemonDivider'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import React from 'react'
import { BOOKMARKLET } from '../constants'
import { ingestionLogic } from '../ingestionLogic'
import './Panels.scss'

export function PanelFooter(): JSX.Element {
    const { platform, onboardingSidebarEnabled } = useValues(ingestionLogic)
    const { setPlatform, setVerify } = useActions(ingestionLogic)
    const { reportIngestionTryWithBookmarkletClicked } = useActions(eventUsageLogic)

    return (
        <Col className="panel-footer">
            <LemonDivider thick dashed style={{ marginTop: 24, marginBottom: 24 }} />
            {platform === BOOKMARKLET ? (
                <div>
                    <LemonButton
                        type="primary"
                        size="large"
                        fullWidth
                        center
                        onClick={() => {
                            reportIngestionTryWithBookmarkletClicked()
                            setVerify(true)
                        }}
                    >
                        Try PostHog with the exploration bookmarklet
                    </LemonButton>
                    <LemonButton
                        className="mt-2"
                        size="large"
                        fullWidth
                        center
                        type="secondary"
                        onClick={() => setPlatform(null)}
                    >
                        Back to setup
                    </LemonButton>
                </div>
            ) : (
                <div>
                    <LemonButton
                        type="primary"
                        size="large"
                        fullWidth
                        center
                        className="mb-2"
                        onClick={() => setVerify(true)}
                    >
                        Continue
                    </LemonButton>
                    <LemonButton
                        className="mt-2"
                        size="large"
                        fullWidth
                        center
                        type="secondary"
                        onClick={() => setVerify(true)}
                    >
                        Skip for now
                    </LemonButton>
                </div>
            )}
            {!onboardingSidebarEnabled && <PanelSupport />}
        </Col>
    )
}

export function PanelHeader({ index }: { index: number }): JSX.Element {
    return (
        <Row align="middle" className="panel-header">
            <span style={index === 1 ? { color: 'black' } : {}}>Step 1</span>
            {index > 1 && (
                <>
                    <IconChevronRight />
                    <span style={index === 2 ? { color: 'black' } : {}}>Step 2</span>
                </>
            )}
            {index > 2 && (
                <>
                    <IconChevronRight />
                    <span style={index === 3 ? { color: 'black' } : {}}>Step 3</span>
                </>
            )}
        </Row>
    )
}

export function PanelSupport(): JSX.Element {
    const { reportIngestionHelpClicked } = useActions(eventUsageLogic)

    return (
        <p className="text-center mb-0 pb-2 mt-4 text-muted" style={{ fontSize: 16 }}>
            Need help?{' '}
            <a
                data-attr="support-docs-help"
                href="https://posthog.com/support"
                target="_blank"
                onClick={() => reportIngestionHelpClicked('support')}
            >
                Visit support
            </a>{' '}
            or{' '}
            <a
                data-attr="ingestion-docs-help"
                href="https://posthog.com/docs/integrate/ingest-live-data"
                target="_blank"
                onClick={() => reportIngestionHelpClicked('documentation')}
            >
                read our documentation
            </a>
        </p>
    )
}
