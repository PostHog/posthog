import { useEffect } from 'react'

import { IconCalendar, IconEye, IconGlobe, IconMouse, IconTrending } from '@posthog/icons'
import { LemonCard, LemonSkeleton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { humanFriendlyNumber } from 'lib/utils'

import { PersonType } from '~/types'

import { PersonPropertiesCard } from './cards/PersonPropertiesCard'
import { PersonInsightsCard } from './cards/PersonInsightsCard'
import { personOverviewLogic } from './PersonOverviewLogic'

interface PersonOverviewProps {
    person: PersonType
}

interface StatCardProps {
    title: string
    value: number | string
    icon: JSX.Element
    loading?: boolean
    subtitle?: string
}

function StatCard({ title, value, icon, loading, subtitle }: StatCardProps): JSX.Element {
    if (loading) {
        return (
            <LemonCard className="p-4 flex flex-col items-center text-center">
                <div className="text-2xl text-muted mb-2">{icon}</div>
                <LemonSkeleton className="h-8 w-16 mb-1" />
                <LemonSkeleton className="h-4 w-20" />
            </LemonCard>
        )
    }

    return (
        <LemonCard className="p-4 flex flex-col items-center text-center">
            <div className="text-2xl text-muted mb-2">{icon}</div>
            <div className="text-2xl font-bold text-default">{value}</div>
            <div className="text-xs text-muted">{title}</div>
            {subtitle && <div className="text-xs text-muted-alt mt-1">{subtitle}</div>}
        </LemonCard>
    )
}

export function PersonOverview({ person }: PersonOverviewProps): JSX.Element {
    const logic = personOverviewLogic({ person })
    const { overviewStats, isLoading } = useValues(logic)
    const { loadOverviewStats } = useActions(logic)

    useEffect(() => {
        if (person?.uuid) {
            loadOverviewStats()
        }
    }, [person?.uuid, loadOverviewStats])

    const formatActivityDate = (dateString: string | null): string => {
        if (!dateString) {
            return 'Unknown'
        }
        return new Date(dateString).toLocaleDateString()
    }

    return (
        <div className="space-y-6">
            {/* Statistics Cards - at the very top */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                <StatCard
                    title="Sessions"
                    value={overviewStats ? humanFriendlyNumber(overviewStats.sessionCount) : 0}
                    icon={<IconMouse />}
                    loading={isLoading}
                />
                <StatCard
                    title="Page Views"
                    value={overviewStats ? humanFriendlyNumber(overviewStats.pageviewCount) : 0}
                    icon={<IconEye />}
                    loading={isLoading}
                />
                <StatCard
                    title="Total Events"
                    value={overviewStats ? humanFriendlyNumber(overviewStats.eventCount) : 0}
                    icon={<IconTrending />}
                    loading={isLoading}
                />
                <StatCard
                    title="First Seen"
                    value={person.created_at ? formatActivityDate(person.created_at) : 'Unknown'}
                    icon={<IconCalendar />}
                    loading={false}
                    subtitle="Person created"
                />
                <StatCard
                    title="Last Seen"
                    value={overviewStats?.lastSeenAt ? formatActivityDate(overviewStats.lastSeenAt) : 'Unknown'}
                    icon={<IconCalendar />}
                    loading={isLoading}
                    subtitle={overviewStats?.lastSeenAt ? 'Last activity' : ''}
                />
            </div>

            {/* Properties Section */}
            <div>
                <div className="flex items-center gap-2 mb-3">
                    <IconGlobe className="text-lg" />
                    <h3 className="font-semibold">Properties</h3>
                </div>
                <PersonPropertiesCard person={person} />
            </div>

            {/* Insights Section */}
            <div>
                <div className="flex items-center gap-2 mb-3">
                    <IconTrending className="text-lg" />
                    <h3 className="font-semibold">Insights</h3>
                </div>
                <PersonInsightsCard person={person} />
            </div>
        </div>
    )
}
