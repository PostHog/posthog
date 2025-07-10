import './EmptyDashboardComponent.scss'

import { useActions } from 'kea'
import React from 'react'

import { IconPlus } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { DASHBOARD_CANNOT_EDIT_MESSAGE } from './DashboardHeader'
import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'

function SkeletonCard({ children, active }: { children: React.ReactNode; active: boolean }): JSX.Element {
    return (
        <div className="deprecated-space-y-4 flex h-full flex-1 flex-col justify-between rounded border p-10">
            <div className="deprecated-space-y-4">
                <LemonSkeleton className="h-4 w-1/3" active={active} />
                <LemonSkeleton className="h-4 w-1/2" active={active} />
            </div>
            {children}
        </div>
    )
}

function SkeletonCardOne({ active }: { active: boolean }): JSX.Element {
    return (
        <SkeletonCard active={active}>
            <div className="flex flex-1 items-end justify-center gap-10">
                {[100, 66, 33].map((height) => (
                    <div
                        key={height}
                        className="border-primary flex h-[80%] w-[15%] flex-col justify-end overflow-hidden rounded border"
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
        <div className="flex flex-1 items-end gap-1">
            {Array(8)
                .fill(0)
                .map((_, index) => {
                    const height = Math.random() * 60 + 10
                    return (
                        <div
                            key={index}
                            className="w-[12.5%]"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                height: `${height}%`,
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
    const { showAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)
    return (
        <div className="EmptyDashboard">
            {!loading && (
                <div className="EmptyDashboard__cta">
                    <h3 className="l3">Dashboard empty</h3>
                    <p>This dashboard sure would look better with some graphs!</p>
                    <div className="mt-4 text-center">
                        <LemonButton
                            data-attr="dashboard-add-graph-header"
                            onClick={showAddInsightToDashboardModal}
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
            <div className="flex h-[30rem] items-center gap-2">
                <SkeletonCardOne active={loading} />
                <SkeletonCardTwo active={loading} />
            </div>
            <div className="EmptyDashboard__fade">
                <div className="flex h-[30rem] items-center gap-2">
                    <SkeletonCardOne active={loading} />
                    <SkeletonCardTwo active={loading} />
                </div>
            </div>
        </div>
    )
}
