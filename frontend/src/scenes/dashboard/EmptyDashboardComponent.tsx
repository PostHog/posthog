import './EmptyDashboardComponent.scss'

import { IconPlus } from '@posthog/icons'
import { useActions } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import React from 'react'

import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'
import { DASHBOARD_CANNOT_EDIT_MESSAGE } from './DashboardHeader'

function SkeletonCard({ children, active }: { children: React.ReactNode; active: boolean }): JSX.Element {
    return (
        <div className="border rounded p-10 h-full deprecated-space-y-4 flex-1 flex flex-col justify-between">
            <div className="deprecated-space-y-4">
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
                        className="border border-border rounded overflow-hidden flex flex-col justify-end w-[15%] h-[80%]"
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
            <div className="flex items-center gap-2 h-[30rem]">
                <SkeletonCardOne active={loading} />
                <SkeletonCardTwo active={loading} />
            </div>
            <div className="EmptyDashboard__fade">
                <div className="flex items-center gap-2 h-[30rem]">
                    <SkeletonCardOne active={loading} />
                    <SkeletonCardTwo active={loading} />
                </div>
            </div>
        </div>
    )
}
