import { kea, useActions, useValues } from 'kea'
import { IconLightBulb, InsightsFunnelsIcon } from 'lib/components/icons'
import { InlineMessage } from 'lib/components/InlineMessage/InlineMessage'
import { Link } from 'lib/components/Link'
import React from 'react'
import { funnelsUpsellLogicType } from './FunnelsUpsellType'
import { ArrowRightOutlined } from '@ant-design/icons'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightLogicProps, InsightType } from '~/types'
import { toParams } from 'lib/utils'
import posthog from 'posthog-js'

const funnelsUpsellLogic = kea<funnelsUpsellLogicType>({
    path: ['scenes', 'insights', 'InsightTabs', 'TrendTab', 'FunnelsUpsell'],
    props: {} as InsightLogicProps,
    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters']],
    }),
    actions: {
        setDestPath: (path: string) => ({ path }),
        optOut: true,
    },
    reducers: {
        destPath: [
            '',
            {
                setDestPath: (_, { path }) => path,
            },
        ],
    },
    listeners: {
        optOut: async () => {
            posthog.capture('funnel cue 2111 - opted out')
        },
    },
    urlToAction: ({ actions }) => ({
        '/insights': (_: any, searchParams: Record<string, any>, hashParams: Record<string, any>) => {
            actions.setDestPath(
                `/insights?${toParams({ ...searchParams, insight: InsightType.FUNNELS })}#${toParams({
                    ...hashParams,
                    funnelCue: '2111',
                })}`
            )
        },
    }),
})

export function FunnelsUpsell({ props }: { props: InsightLogicProps }): JSX.Element {
    const logic = funnelsUpsellLogic(props)
    const { optOut } = useActions(logic)
    const { destPath } = useValues(logic)

    return (
        <div className="mt">
            <InlineMessage
                closable
                icon={<IconLightBulb style={{ color: 'var(--warning)', fontSize: '1.3em' }} />}
                onClose={optOut}
            >
                <div>
                    Looks like you have multiple events. A funnel can help better visualize your user's progression
                    across each event.{' '}
                    <Link to={destPath}>
                        Try this graph as a <InsightsFunnelsIcon /> funnel <ArrowRightOutlined />
                    </Link>
                </div>
            </InlineMessage>
        </div>
    )
}
