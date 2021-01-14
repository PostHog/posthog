import { CardContainer } from 'scenes/ingestion/CardContainer'
import { Collapse, Tag } from 'antd'
import React from 'react'
import { useActions, useValues } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { BulbOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { JSInstructions } from '../frameworks'
import { JSSnippet } from 'lib/components/JSSnippet'

export function AutocapturePanel(): JSX.Element {
    const { index, totalSteps } = useValues(ingestionLogic)
    const { setPlatform, setVerify } = useActions(ingestionLogic)
    return (
        <CardContainer
            index={index}
            totalSteps={totalSteps}
            nextButton={true}
            onSubmit={() => setVerify(true)}
            onBack={() => setPlatform(null)}
        >
            <Collapse>
                <Collapse.Panel
                    header={
                        <>
                            <BulbOutlined style={{ color: 'var(--warning)' }} /> <b>Just exploring?</b> Immediately run
                            PostHog in your website for some initial exploring.
                        </>
                    }
                    key="1"
                >
                    Hello world!
                </Collapse.Panel>
            </Collapse>
            <div style={{ marginTop: 16 }}>
                <h2>
                    Option 1. Autocapture <Tag color="green">Recommended</Tag>
                </h2>
                <p>
                    Faster option. Particularly recommended for new projects where you don't know what your analytics
                    will look like just yet. Just add this snippet to your website and we'll{' '}
                    <b>automatically capture page views, sessions and all relevant interactions</b> within your website.{' '}
                    <Link to="https://posthog.com/product-features/event-autocapture" target="_blank" rel="noopener">
                        Learn more
                    </Link>
                    .
                </p>
                <b>Steps:</b>
                <ol>
                    <li>
                        Insert this snippet in your website within the <code>&lt;head&gt;</code> tag. <JSSnippet />
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
                    <Link to="https://posthog.com/docs/integrations/js-integration/" target="_blank" rel="noopener">
                        Learn more
                    </Link>
                    .
                    <JSInstructions />
                </p>
            </div>
        </CardContainer>
    )
}
