import { CardContainer } from 'scenes/ingestion/CardContainer'
import { Alert, Collapse, Tag } from 'antd'
import React from 'react'
import { useActions, useValues } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { BookOutlined, BulbOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { JSInstructions } from '../frameworks'
import { JSSnippet } from 'lib/components/JSSnippet'
import { JSBookmarklet } from 'lib/components/JSBookmarklet'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

export function AutocapturePanel(): JSX.Element {
    const { index, totalSteps, framework } = useValues(ingestionLogic)
    const { setPlatform, setVerify } = useActions(ingestionLogic)
    const { currentTeam } = useValues(teamLogic)
    const { reportIngestionBookmarkletCollapsible } = useActions(eventUsageLogic)

    const handlePanelChange = (shownPanels: string | string[]): void => {
        if (typeof shownPanels === 'string') {
            reportIngestionBookmarkletCollapsible([shownPanels])
        } else {
            reportIngestionBookmarkletCollapsible(shownPanels)
        }
    }

    const scrollToSdk = (e: HTMLDivElement): void => {
        if (framework?.toString() === 'PURE_JS') {
            e?.scrollIntoView()
        }
    }

    return (
        <CardContainer
            index={index}
            totalSteps={totalSteps}
            nextButton={true}
            onSubmit={() => setVerify(true)}
            onBack={() => setPlatform(null)}
        >
            {currentTeam && (
                <Collapse onChange={handlePanelChange}>
                    <Collapse.Panel
                        header={
                            <>
                                <BulbOutlined style={{ color: 'var(--warning)' }} /> <b>Just exploring?</b> Immediately
                                run PostHog on your website for some initial exploring.
                            </>
                        }
                        key="bookmarklet"
                    >
                        If you want to quickly test PostHog in your website <b>without changing any code</b>, try out
                        our bookmarklet.
                        <div>
                            <b>Steps:</b>
                        </div>
                        <ol>
                            <li>
                                <b>Drag</b> the link (<BookOutlined />) below to your bookmarks toolbar.{' '}
                            </li>
                            <li>Open the website you want to track and click on the bookmark you just added.</li>
                            <li>Click continue below and see events coming in.</li>
                        </ol>
                        <div className="mt">
                            <JSBookmarklet team={currentTeam} />
                        </div>
                        <div className="mt">
                            <Alert
                                type="warning"
                                message={
                                    <>
                                        Please note this installation is only{' '}
                                        <b>temporary, intended just for testing</b>. It will only work for the current
                                        page and only in your browser session.
                                    </>
                                }
                            />
                        </div>
                    </Collapse.Panel>
                </Collapse>
            )}
            <div style={{ marginTop: 16 }}>
                <h2>
                    Option 1. Code snippet <Tag color="green">Recommended</Tag>
                </h2>
                <p>
                    Just add this snippet to your website and we'll{' '}
                    <b>automatically capture page views, sessions and all relevant interactions</b> within your website.{' '}
                    <Link
                        to="https://posthog.com/product-features/event-autocapture?utm_medium=in-product&utm_campaign=ingestion-web"
                        target="_blank"
                        rel="noopener"
                    >
                        Learn more
                    </Link>
                    .
                </p>
                <b>Steps:</b>
                <ol>
                    <li>
                        Insert this snippet in your website within the <code className="code">&lt;head&gt;</code> tag.{' '}
                        <JSSnippet />
                    </li>
                    <li>
                        <b>Visit your site</b> to generate some initial events.
                    </li>
                </ol>
            </div>
            <div ref={scrollToSdk} style={{ marginTop: 32 }}>
                <h2>Option 2. Javascript Library</h2>
                <p>
                    Use this option if you want more granular control of how PostHog runs in your website and the events
                    you capture. Recommended for teams with more stable products and more defined analytics
                    requirements.{' '}
                    <Link
                        to="https://posthog.com/docs/integrations/js-integration/?utm_medium=in-product&utm_campaign=ingestion-web"
                        target="_blank"
                        rel="noopener"
                    >
                        Learn more
                    </Link>
                    .
                </p>
                <JSInstructions />
            </div>
        </CardContainer>
    )
}
