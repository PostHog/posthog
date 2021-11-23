import { IconLightBulb, InsightsFunnelsIcon } from 'lib/components/icons'
import { InlineMessage } from 'lib/components/InlineMessage/InlineMessage'
import { Link } from 'lib/components/Link'
import React from 'react'
import { ArrowRightOutlined } from '@ant-design/icons'

export function FunnelsUpsell(): JSX.Element {
    return (
        <div className="mt">
            <InlineMessage closable icon={<IconLightBulb style={{ color: 'var(--warning)', fontSize: '1.3em' }} />}>
                <div>
                    Looks like you have multiple events. A funnel can help better visualize your user's progression
                    across each event.{' '}
                    <Link>
                        Try this graph as a <InsightsFunnelsIcon /> funnel <ArrowRightOutlined />
                    </Link>
                </div>
            </InlineMessage>
        </div>
    )
}
