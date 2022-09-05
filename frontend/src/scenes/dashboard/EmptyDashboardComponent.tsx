import React from 'react'
import { dashboardLogic } from './dashboardLogic'
import { useValues } from 'kea'
import { urls } from 'scenes/urls'
import { LemonButton } from 'lib/components/LemonButton'
import { Skeleton } from 'lib/components/Skeleton/Skeleton'
import { IconPlus } from 'lib/components/icons'
import './EmptyDashboardComponent.scss'

function SkeletonCard({ children, active }: { children: React.ReactNode; active: boolean }): JSX.Element {
    return (
        <div className="border rounded p-10 h-full space-y-4 flex-1 flex flex-col justify-between">
            <div className="space-y-4">
                <Skeleton width={'30%'} active={active} />
                <Skeleton width={'50%'} active={active} />
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
                        className="border border-border-light rounded-2xl overflow-hidden flex flex-col justify-end"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: '15%', height: '80%' }}
                    >
                        <Skeleton active={active} height={`${height}%`} />
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
                    return <Skeleton active={active} key={index} height={`${height}%`} width={'12.5%'} />
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

export function EmptyDashboardComponent({ loading }: { loading: boolean }): JSX.Element {
    const { dashboard } = useValues(dashboardLogic)

    return (
        <div className="EmptyDashboard">
            {!loading && (
                <div className="EmptyDashboard__cta">
                    <div className="border rounded p-6 shadow bg-white">
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
                            >
                                Add insight
                            </LemonButton>
                        </div>
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
