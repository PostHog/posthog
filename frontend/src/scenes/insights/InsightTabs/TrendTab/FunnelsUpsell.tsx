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
import clsx from 'clsx'
import './FunnelsUpsell.scss'

const funnelsUpsellLogic = kea<funnelsUpsellLogicType>({
    path: ['scenes', 'insights', 'InsightTabs', 'TrendTab', 'FunnelsUpsell'],
    props: {} as InsightLogicProps,
    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters']],
        actions: [insightLogic(props), ['setFilters']],
    }),
    actions: {
        setDestPath: (path: string) => ({ path }),
        optOut: true,
        setShouldShow: (show: boolean) => ({ show }),
        setPermanentOptOut: true,
    },
    reducers: {
        destPath: [
            '',
            {
                setDestPath: (_, { path }) => path,
            },
        ],
        _shouldShow: [
            false, // Whether the conditions are met to show the upsell (right filters, user has not used funnels recently)
            {
                setShouldShow: (_, { show }) => show,
            },
        ],
        permanentOptOut: [
            false,
            {
                setPermanentOptOut: () => true,
            },
        ],
    },
    listeners: ({ actions, values }) => ({
        optOut: async () => {
            posthog.capture('funnel cue 7301 - opted out')
            window.localStorage.setItem('p7301', '1')
            actions.setPermanentOptOut()
        },
        setFilters: async ({ filters }) => {
            const step_count = (filters.events?.length ?? 0) + (filters.actions?.length ?? 0)
            if (filters.insight === InsightType.TRENDS && step_count >= 2) {
                actions.setShouldShow(true)
                !values.permanentOptOut && posthog.capture('funnel cue 7301 - shown', { step_count })
            } else {
                actions.setShouldShow(false)
            }
        },
    }),
    selectors: {
        shown: [
            (s) => [s._shouldShow, s.permanentOptOut],
            (shouldShow, permanentOptout): boolean => shouldShow && !permanentOptout,
        ],
    },
    events: ({ actions }) => ({
        afterMount: async () => {
            if (window.localStorage.getItem('p7301')) {
                actions.setPermanentOptOut()
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '/insights': (_: any, searchParams: Record<string, any>, hashParams: Record<string, any>) => {
            actions.setDestPath(
                `/insights?${toParams({ ...searchParams, insight: InsightType.FUNNELS })}#${toParams({
                    ...hashParams,
                    funnelCue: '7301',
                })}`
            )
        },
    }),
})

export function FunnelsUpsell({ props }: { props: InsightLogicProps }): JSX.Element | null {
    const logic = funnelsUpsellLogic(props)
    const { optOut } = useActions(logic)
    const { destPath, shown } = useValues(logic)

    return (
        <div className={clsx('funnels-product-cue', shown && 'shown')}>
            <InlineMessage
                closable
                icon={<IconLightBulb style={{ color: 'var(--warning)', fontSize: '1.3em' }} />}
                onClose={optOut}
            >
                <div>
                    Looks like you have multiple events. A funnel can help better visualize your user's progression
                    across each event.{' '}
                    <Link to={destPath} data-attr="funnel-cue-7301">
                        Try this graph as a <InsightsFunnelsIcon /> funnel <ArrowRightOutlined />
                    </Link>
                </div>
            </InlineMessage>
        </div>
    )
}
