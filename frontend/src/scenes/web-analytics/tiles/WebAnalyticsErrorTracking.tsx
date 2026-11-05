import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'
import { useCallback } from 'react'

import * as panicPng from '@posthog/brand/hoggies/png/panic'
import * as starPng from '@posthog/brand/hoggies/png/star'
import { errorTrackingSetupLogic } from '@posthog/products-error-tracking/frontend/emptyState/errorTrackingSetupLogic'

import { pngHoggie } from 'lib/brand/hoggies'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { ErrorTrackingTile } from 'scenes/web-analytics/common'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { Query } from '~/queries/Query/Query'
import { ErrorTrackingIssue, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumnComponent } from '~/queries/types'

const HedgehogStar = pngHoggie(starPng)
const HedgehogPanic = pngHoggie(panicPng)

export const CustomGroupTitleColumn: QueryContextColumnComponent = (props) => {
    const record = props.record as ErrorTrackingIssue

    return (
        <div className="flex items-start gap-x-1.5 group">
            <LemonTableLink
                target="_blank"
                title={record.name || 'Unknown Type'}
                description={<div className="line-clamp-1">{record.description}</div>}
                className="flex"
                to={urls.errorTrackingIssue(record.id)}
            />
        </div>
    )
}

const LastSeenColumn = ({ record }: { record: unknown }): JSX.Element => {
    const last_seen = (record as ErrorTrackingIssue).last_seen
    return <TZLabel time={last_seen} className="border-dotted border-b" />
}

const CountColumn = ({ record, columnName }: { record: unknown; columnName: string }): JSX.Element => {
    const aggregations = (record as ErrorTrackingIssue).aggregations!
    const count = aggregations[columnName as 'occurrences' | 'users']
    return <>{humanFriendlyLargeNumber(count)}</>
}

const issuesContext: QueryContext = {
    extraDataTableQueryFeatures: [QueryFeature.hideLoadNextButton],
    showOpenEditorButton: false,
    showQueryEditor: false,
    columns: {
        error: {
            align: 'left',
            render: CustomGroupTitleColumn,
        },
        users: {
            align: 'right',
            render: CountColumn,
        },
        occurrences: {
            align: 'right',
            render: CountColumn,
        },
        last_seen: {
            title: 'Last seen',
            align: 'right',
            render: LastSeenColumn,
        },
    },
}

const emptyIssuesContext: QueryContext = {
    ...issuesContext,
    emptyStateIcon: <HedgehogStar className="w-32 mb-2" />,
    emptyStateHeading: 'No errors found!',
    emptyStateDetail: 'Keep up the great work!',
}

export const WebAnalyticsErrorTrackingTile = ({ tile }: { tile: ErrorTrackingTile }): JSX.Element => {
    const { layout, query } = tile
    const to = urls.errorTracking()
    const { addProductIntentForCrossSell } = useActions(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    useMountedLogic(errorTrackingSetupLogic)
    const { status: errorTrackingStatus } = useValues(
        productSetupStatusLogic({ productKey: ProductKey.ERROR_TRACKING })
    )
    const useTileHeaderV2 = featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_TILE_HEADER_V2] === 'test'

    const crossSellToErrorTracking = useCallback((): void => {
        addProductIntentForCrossSell({
            from: ProductKey.WEB_ANALYTICS,
            to: ProductKey.ERROR_TRACKING,
            intent_context: ProductIntentContext.WEB_ANALYTICS_ERRORS,
        })
    }, [addProductIntentForCrossSell])

    const viewAllButton = (
        <LemonButton to={to} icon={<IconOpenInNew />} onClick={crossSellToErrorTracking} size="small" type="secondary">
            View all
        </LemonButton>
    )

    // Without error tracking set up, an empty table says nothing, so skip the query and pitch the product.
    // While detection is loading the query also waits, so a project without it never pays for the request.
    // If detection fails (`unknown`) the query runs with generic copy: that makes no claim about setup.
    const needsSetup = errorTrackingStatus === 'needs-setup'
    const body = needsSetup ? (
        <ProductIntroduction
            thingName="error tracking"
            titleOverride="Error tracking is not set up"
            description="See the exceptions your visitors hit, grouped by issue and linked to the session they happened in."
            actionElementOverride={
                <LemonButton
                    to={to}
                    onClick={crossSellToErrorTracking}
                    type="primary"
                    data-attr="web-analytics-error-tracking-setup"
                >
                    Set up error tracking
                </LemonButton>
            }
            customHog={HedgehogPanic}
            hogLayout="vertical"
            hogClassName="w-24 sm:w-24 lg:w-24 mb-2"
            className="my-0 p-4"
        />
    ) : errorTrackingStatus === 'loading' ? (
        <LemonSkeleton className="h-40 m-2" />
    ) : (
        <Query
            attachTo={webAnalyticsLogic}
            query={query}
            embedded={true}
            context={
                errorTrackingStatus === 'has-data' || errorTrackingStatus === 'waiting-for-data'
                    ? emptyIssuesContext
                    : issuesContext
            }
        />
    )

    return (
        <div
            className={clsx(
                'col-span-1 row-span-1 flex flex-col',
                layout.colSpanClassName ?? 'md:col-span-1',
                layout.rowSpanClassName ?? 'md:row-span-1',
                layout.orderWhenLargeClassName ?? '2xl:order-12',
                layout.className
            )}
        >
            {useTileHeaderV2 ? (
                <div className="border rounded bg-surface-primary flex-1 flex flex-col py-2 px-1">
                    <div className="flex flex-row items-center self-stretch gap-2 min-h-10 px-3 py-2">
                        <h2 className="flex-1 m-0 text-base font-semibold">Error tracking</h2>
                        {!needsSetup && viewAllButton}
                    </div>
                    {body}
                </div>
            ) : (
                <>
                    <h2 className="m-0 mb-3">Error tracking</h2>
                    <div className="border rounded bg-surface-primary flex-1 flex flex-col py-2 px-1">{body}</div>
                    {!needsSetup && <div className="flex flex-row-reverse my-2">{viewAllButton}</div>}
                </>
            )}
        </div>
    )
}
