import { CardContainer } from 'scenes/ingestion/CardContainer'
import { Alert, Collapse, Tag } from 'antd'
import React from 'react'
import { useActions, useValues } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { BulbOutlined, BookOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { JSInstructions } from '../frameworks'
import { JSSnippet } from 'lib/components/JSSnippet'
import { JSBookmarklet } from 'lib/components/JSBookmarklet'
import { userLogic } from 'scenes/userLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export function AutocapturePanel(): JSX.Element {
    const { index, totalSteps } = useValues(ingestionLogic)
    const { setPlatform, setVerify } = useActions(ingestionLogic)
    const { user } = useValues(userLogic)
    const { reportIngestionBookmarkletCollapsible } = useActions(eventUsageLogic)
    return (
        <CardContainer
            index={index}
            totalSteps={totalSteps}
            nextButton={true}
            onSubmit={() => setVerify(true)}
            onBack={() => setPlatform(null)}
        >
            {user?.team && (
                <Collapse onChange={(shownPanels) => reportIngestionBookmarkletCollapsible(shownPanels)}>
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
                            <JSBookmarklet team={user.team} />
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
                    Faster option. Particularly recommended for new projects where you don't know what your analytics
                    will look like just yet. Just add this snippet to your website and we'll{' '}
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
            <div style={{ marginTop: 32 }}>
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
