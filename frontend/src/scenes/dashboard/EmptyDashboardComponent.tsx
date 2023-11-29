import './EmptyDashboardComponent.scss'

import { useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconPlus } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import React from 'react'
import { urls } from 'scenes/urls'

import { DASHBOARD_CANNOT_EDIT_MESSAGE } from './DashboardHeader'
import { dashboardLogic } from './dashboardLogic'

function SkeletonCard({ children, active }: { children: React.ReactNode; active: boolean }): JSX.Element {
    const is3000 = useFeatureFlag('POSTHOG_3000')
    const rounded = is3000 ? 'rounded-md' : 'rounded'

    return (
        <div className={`border ${rounded} p-10 h-full space-y-4 flex-1 flex flex-col justify-between`}>
            <div className="space-y-4">
                <LemonSkeleton className="w-1/3 h-4" active={active} />
                <LemonSkeleton className="w-1/2 h-4" active={active} />
            </div>
            {children}
        </div>
    )
}

function SkeletonCardOne({ active }: { active: boolean }): JSX.Element {
    return (
        <SkeletonCard active={active}>
            <div className="flex justify-center flex-1 items-end gap-10">
                {[100, 66, 33].map((height) => (
                    <div
                        key={height}
                        className="border border-border-light rounded overflow-hidden flex flex-col justify-end"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: '15%', height: '80%' }}
                    >
                        {/* eslint-disable-next-line react/forbid-dom-props */}
                        <div style={{ height: `${height}%` }}>
                            <LemonSkeleton active={active} className="h-full w-full" />
                        </div>
                    </div>
                ))}
            </div>
        </SkeletonCard>
    )
}

function SkeletonBarsRaw({ active }: { active: boolean }): JSX.Element {
    return (
        <div className="flex items-end gap-1 flex-1">
            {Array(8)
                .fill(0)
                .map((_, index) => {
                    const height = Math.random() * 60 + 10
                    return (
                        <div
                            key={index}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                height: `${height}%`,
                                width: '12.5%',
                            }}
                        >
                            <LemonSkeleton active={active} className="h-full w-full" />
                        </div>
                    )
                })}
        </div>
    )
}
/** This component looks different on each render due to Math.random() calls within, so it's memoized to avoid that. */
const SkeletonBars = React.memo(SkeletonBarsRaw)

function SkeletonCardTwo({ active }: { active: boolean }): JSX.Element {
    return (
        <SkeletonCard active={active}>
            <SkeletonBars active={active} />
        </SkeletonCard>
    )
}

export function EmptyDashboardComponent({ loading, canEdit }: { loading: boolean; canEdit: boolean }): JSX.Element {
    const { dashboard } = useValues(dashboardLogic)

    return (
        <div className="EmptyDashboard">
            {!loading && (
                <div className="EmptyDashboard__cta">
                    <h3 className="l3">Dashboard empty</h3>
                    <p>This dashboard sure would look better with some graphs!</p>
                    <div className="mt-4 text-center">
                        <LemonButton
                            data-attr="dashboard-add-graph-header"
                            to={urls.insightNew(undefined, dashboard?.id)}
                            type="primary"
                            icon={<IconPlus />}
                            center
                            fullWidth
                            disabledReason={canEdit ? null : DASHBOARD_CANNOT_EDIT_MESSAGE}
                        >
                            Add insight
                        </LemonButton>
                    </div>
                </div>
            )}
            {/*  eslint-disable-next-line react/forbid-dom-props */}
            <div className="flex items-center gap-2" style={{ height: '30rem' }}>
                <SkeletonCardOne active={loading} />
                <SkeletonCardTwo active={loading} />
            </div>
            <div className="EmptyDashboard__fade">
                {/*  eslint-disable-next-line react/forbid-dom-props */}
                <div className="flex items-center gap-2" style={{ height: '30rem' }}>
                    <SkeletonCardOne active={loading} />
                    <SkeletonCardTwo active={loading} />
                </div>
            </div>
        </div>
    )
}
