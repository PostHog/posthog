import { useActions, useValues } from 'kea'
import { IconLightBulb } from 'lib/components/icons'
import { InlineMessage } from 'lib/components/InlineMessage/InlineMessage'
import React from 'react'
import clsx from 'clsx'
import './FunnelsCue.scss'
import { funnelsCueLogic } from 'scenes/insights/views/Trends/funnelsCueLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'
import { InsightType } from '~/types'
import { LemonButton } from '@posthog/lemon-ui'

export function FunnelsCue({ tooltipPosition }: { tooltipPosition?: number }): JSX.Element | null {
    const { insightProps, filters } = useValues(insightLogic)
    const { optOut } = useActions(funnelsCueLogic(insightProps))
    const { shown } = useValues(funnelsCueLogic(insightProps))

    return (
        <div className={clsx('funnels-product-cue', shown && 'shown')}>
            <InlineMessage
                closable
                icon={<IconLightBulb style={{ color: 'var(--warning)', fontSize: '1.3em' }} />}
                onClose={() => optOut(true)}
            >
                <div className="flex items-center">
                    <div style={{ paddingRight: 16 }}>
                        Looks like you have multiple events. A funnel can help better visualize your user's progression
                        across each event.
                    </div>
                    <LemonButton
                        to={urls.insightNew({ ...filters, insight: InsightType.FUNNELS })}
                        data-attr="funnel-cue-7301"
                    >
                        Try this insight as a funnel
                    </LemonButton>
                </div>
            </InlineMessage>
            {tooltipPosition && (
                <div
                    className="tooltip-arrow"
                    style={{
                        left: tooltipPosition,
                    }}
                />
            )}
        </div>
    )
}
