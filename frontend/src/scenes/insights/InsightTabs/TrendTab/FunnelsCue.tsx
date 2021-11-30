import { kea, useActions, useValues } from 'kea'
import { IconLightBulb } from 'lib/components/icons'
import { InlineMessage } from 'lib/components/InlineMessage/InlineMessage'
import { Link } from 'lib/components/Link'
import React from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightLogicProps, InsightType } from '~/types'
import { toParams } from 'lib/utils'
import posthog from 'posthog-js'
import clsx from 'clsx'
import './FunnelsCue.scss'
import { funnelsCueLogicType } from './FunnelsCueType'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Button } from 'antd'

const funnelsCueLogic = kea<funnelsCueLogicType>({
    path: ['scenes', 'insights', 'InsightTabs', 'TrendTab', 'FunnelsCue'],
    props: {} as InsightLogicProps,
    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters', 'isFirstLoad'], featureFlagLogic, ['featureFlags']],
        actions: [insightLogic(props), ['setFilters'], featureFlagLogic, ['setFeatureFlags']],
    }),
    actions: {
        setDestPath: (path: string) => ({ path }),
        optOut: (userOptedOut: boolean) => ({ userOptedOut }),
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
            false,
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
        optOut: async ({ userOptedOut }) => {
            posthog.capture('funnel cue 7301 - terminated', { user_opted_out: userOptedOut })
            posthog.people.set({ funnels_cue_3701_opt_out: true })
            // funnels_cue_3701_opt_out -> will add the user to a FF that will permanently exclude the user
            actions.setPermanentOptOut()
        },
        setFilters: async ({ filters }) => {
            if (!values.featureFlags[FEATURE_FLAGS.FUNNELS_CUE_ENABLED]) {
                return
            }
            const step_count = (filters.events?.length ?? 0) + (filters.actions?.length ?? 0)
            if (!values.isFirstLoad && filters.insight === InsightType.TRENDS && step_count >= 3) {
                actions.setShouldShow(true)
                !values.permanentOptOut && posthog.capture('funnel cue 7301 - shown', { step_count })
            } else if (values.shown && filters.insight === InsightType.FUNNELS) {
                actions.optOut(false)
            } else {
                actions.setShouldShow(false)
            }
        },
        setFeatureFlags: async ({ flags }) => {
            if (flags[FEATURE_FLAGS.FUNNELS_CUE_OPT_OUT]) {
                actions.setPermanentOptOut()
            }
        },
    }),
    selectors: {
        shown: [
            (s) => [s._shouldShow, s.permanentOptOut],
            (shouldShow, permanentOptout): boolean => shouldShow && !permanentOptout,
        ],
    },
    events: ({ actions, values }) => ({
        afterMount: async () => {
            if (values.featureFlags[FEATURE_FLAGS.FUNNELS_CUE_OPT_OUT]) {
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

export function FunnelsCue({
    props,
    tooltipPosition,
}: {
    props: InsightLogicProps
    tooltipPosition?: number
}): JSX.Element | null {
    const logic = funnelsCueLogic(props)
    const { optOut } = useActions(logic)
    const { destPath, shown } = useValues(logic)

    return (
        <div className={clsx('funnels-product-cue', shown && 'shown')}>
            <InlineMessage
                closable
                icon={<IconLightBulb style={{ color: 'var(--warning)', fontSize: '1.3em' }} />}
                onClose={() => optOut(true)}
            >
                <div className="flex-center">
                    <div style={{ paddingRight: 16 }}>
                        Looks like you have multiple events. A funnel can help better visualize your user's progression
                        across each event.
                    </div>
                    <Link
                        to={destPath}
                        data-attr="funnel-cue-7301"
                        tag={<Button style={{ color: 'var(--primary)', fontWeight: 500 }} />}
                    >
                        Try this insight as a funnel
                    </Link>
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
