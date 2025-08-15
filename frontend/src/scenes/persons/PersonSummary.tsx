import { useEffect } from 'react'

import {
    IconCalendar,
    IconEye,
    IconFlag,
    IconGlobe,
    IconLaptop,
    IconLetter,
    IconMouse,
    IconPerson,
    IconPulse,
    IconTrending,
} from '@posthog/icons'
import { LemonCard, LemonSkeleton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { humanFriendlyNumber } from 'lib/utils'
import {
    IconAndroidOS,
    IconAppleIOS,
    IconChrome,
    IconFirefox,
    IconLinux,
    IconMacOS,
    IconMicrosoftEdge,
    IconMonitor,
    IconOpera,
    IconPhone,
    IconSafari,
    IconTablet,
    IconWindows,
} from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { Query } from '~/queries/Query/Query'
import { CalendarHeatmapQuery, NodeKind } from '~/queries/schema/schema-general'
import { PersonType, PropertyFilterType } from '~/types'

import { ImportantProperty, personSummaryLogic } from './PersonSummaryLogic'

interface PersonSummaryProps {
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

interface PropertyCardProps {
    property: ImportantProperty
}

function PropertyRow({ property }: PropertyCardProps): JSX.Element {
    const formatValue = (value: unknown): string => {
        if (typeof value === 'boolean') {
            return value ? 'Yes' : 'No'
        }
        if (typeof value === 'number') {
            return humanFriendlyNumber(value)
        }
        if (typeof value === 'string' && value.length > 50) {
            return value.substring(0, 47) + '...'
        }
        return String(value)
    }

    const getPropertyLabel = (key: string): string => {
        const labelMap: Record<string, string> = {
            // Email
            email: 'Email',
            $email: 'Email',

            // Name
            name: 'Name',
            $name: 'Name',
            first_name: 'First Name',
            last_name: 'Last Name',

            // Browser
            $browser: 'Browser',
            $browser_version: 'Browser Version',

            // OS & Device
            $os: 'Operating System',
            $device_type: 'Device Type',

            // Location
            $geoip_country_name: 'Country',
            $geoip_city_name: 'City',
            $geoip_time_zone: 'Time Zone',
            $geoip_continent_name: 'Continent',
            $initial_geoip_country_name: 'Initial Country',
            $initial_geoip_city_name: 'Initial City',
            $initial_geoip_continent_name: 'Initial Continent',
            $initial_geoip_time_zone: 'Initial Time Zone',

            // UTM
            utm_source: 'UTM Source',
            utm_medium: 'UTM Medium',
            utm_campaign: 'UTM Campaign',
            utm_content: 'UTM Content',

            // URL
            $initial_current_url: 'Landing Page',
            $initial_referring_domain: 'Referring Domain',

            // Demographics
            company: 'Company',
            title: 'Job Title',
            phone: 'Phone',
        }

        return (
            labelMap[key] ||
            key
                .replace(/^\$/, '')
                .replace(/_/g, ' ')
                .replace(/\b\w/g, (l) => l.toUpperCase())
        )
    }

    // Convert PostHog icon identifiers and emojis to PostHog icons (for Current properties only)
    const getSymbolIcon = (symbol?: string): JSX.Element | null => {
        if (!symbol) {
            return null
        }

        const symbolToIcon: Record<string, JSX.Element> = {
            // PostHog OS icons
            macos: <IconMacOS className="w-4 h-4" />,
            windows: <IconWindows className="w-4 h-4" />,
            linux: <IconLinux className="w-4 h-4" />,
            android: <IconAndroidOS className="w-4 h-4" />,
            ios: <IconAppleIOS className="w-4 h-4" />,
            other: <IconLaptop className="w-4 h-4" />,

            // PostHog browser icons
            chrome: <IconChrome className="w-4 h-4" />,
            firefox: <IconFirefox className="w-4 h-4" />,
            safari: <IconSafari className="w-4 h-4" />,
            edge: <IconMicrosoftEdge className="w-4 h-4" />,
            opera: <IconOpera className="w-4 h-4" />,

            // PostHog device icons
            mobile: <IconPhone className="w-4 h-4" />,
            tablet: <IconTablet className="w-4 h-4" />,
            desktop: <IconMonitor className="w-4 h-4" />,

            // Fallback for emojis still in use
            '📧': <IconLetter className="w-4 h-4 text-blue" />,
            '👤': <IconPerson className="w-4 h-4 text-green" />,
            '🏙️': <IconGlobe className="w-4 h-4 text-cyan" />,
            '🕐': <IconCalendar className="w-4 h-4 text-gray" />,
            '🌍': <IconGlobe className="w-4 h-4 text-green" />,
            '🏢': <IconFlag className="w-4 h-4 text-orange" />,
            '💼': <IconFlag className="w-4 h-4 text-blue" />,
            '📞': <IconFlag className="w-4 h-4 text-green" />,
        }

        return symbolToIcon[symbol] || <span className="text-sm">{symbol}</span>
    }

    // Check if this is an acquisition property (should show label instead of symbol)
    const isAcquisitionProperty = (key: string): boolean => {
        return key.startsWith('$initial_') || key.startsWith('utm_')
    }

    const hasSymbol = property.symbol && !isAcquisitionProperty(property.key)

    if (hasSymbol) {
        // Current properties: show symbol + value
        return (
            <div className="flex items-center gap-2 py-1.5 px-2 hover:bg-accent/20 rounded">
                <div className="flex-shrink-0">{getSymbolIcon(property.symbol)}</div>
                <div className="text-sm font-medium text-default truncate">{formatValue(property.value)}</div>
            </div>
        )
    }
    // Acquisition properties: show label + value with reduced spacing and truncation
    const fullValue = formatValue(property.value)
    const truncatedValue = fullValue.length > 40 ? fullValue.substring(0, 37) + '...' : fullValue
    const shouldShowTooltip = fullValue.length > 40

    return (
        <div className="flex items-center gap-2 py-1.5 px-2 hover:bg-accent/20 rounded">
            <div className="text-xs text-muted font-medium min-w-0 flex-shrink-0">{getPropertyLabel(property.key)}</div>
            {shouldShowTooltip ? (
                <Tooltip title={String(property.value)}>
                    <div className="text-sm font-medium text-default truncate cursor-default">{truncatedValue}</div>
                </Tooltip>
            ) : (
                <div className="text-sm font-medium text-default truncate">{truncatedValue}</div>
            )}
        </div>
    )
}

export function PersonSummary({ person }: PersonSummaryProps): JSX.Element {
    const logic = personSummaryLogic({ person })
    const { summaryStats, importantProperties, isLoading } = useValues(logic)
    const { loadSummaryStats } = useActions(logic)

    useEffect(() => {
        if (person?.uuid) {
            loadSummaryStats()
        }
    }, [person?.uuid, loadSummaryStats])

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
                    value={summaryStats ? humanFriendlyNumber(summaryStats.sessionCount) : 0}
                    icon={<IconMouse />}
                    loading={isLoading}
                />
                <StatCard
                    title="Page Views"
                    value={summaryStats ? humanFriendlyNumber(summaryStats.pageviewCount) : 0}
                    icon={<IconEye />}
                    loading={isLoading}
                />
                <StatCard
                    title="Total Events"
                    value={summaryStats ? humanFriendlyNumber(summaryStats.eventCount) : 0}
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
                    value={summaryStats?.lastSeenAt ? formatActivityDate(summaryStats.lastSeenAt) : 'Unknown'}
                    icon={<IconCalendar />}
                    loading={isLoading}
                    subtitle={summaryStats?.lastSeenAt ? 'Last activity' : ''}
                />
            </div>

            {/* Properties and Activity - Side by Side */}
            <div className="grid grid-cols-1 lg:grid-cols-10 gap-6">
                {/* Key Properties */}
                <div className="lg:col-span-3">
                    <div className="flex items-center gap-2 mb-3">
                        <IconGlobe className="text-lg" />
                        <h3 className="font-semibold">Properties</h3>
                        <span className="text-xs text-muted">({importantProperties.length})</span>
                    </div>

                    {importantProperties.length === 0 ? (
                        <LemonCard className="p-3 text-center">
                            <div className="text-muted text-sm">No properties found yet</div>
                            <div className="text-xs text-muted-alt mt-1">
                                Properties like location, UTM parameters, and demographics will appear here as they're
                                collected
                            </div>
                        </LemonCard>
                    ) : (
                        <LemonCard className="p-3">
                            {(() => {
                                // Group properties by current vs acquisition
                                const isAcquisitionProperty = (key: string): boolean => {
                                    return (
                                        key.startsWith('$initial_') ||
                                        key.startsWith('utm_') ||
                                        key === '$initial_current_url' ||
                                        key === '$initial_referring_domain'
                                    )
                                }

                                const currentProperties = importantProperties.filter(
                                    (p) => !isAcquisitionProperty(p.key)
                                )
                                const acquisitionProperties = importantProperties.filter((p) =>
                                    isAcquisitionProperty(p.key)
                                )

                                const renderSection = (
                                    title: string,
                                    icon: JSX.Element,
                                    properties: ImportantProperty[]
                                ): JSX.Element | null => {
                                    if (properties.length === 0) {
                                        return null
                                    }

                                    return (
                                        <div className="mb-4 last:mb-0">
                                            <div className="flex items-center gap-2 mb-2">
                                                {icon}
                                                <h4 className="text-xs font-semibold text-muted uppercase tracking-wide">
                                                    {title}
                                                </h4>
                                            </div>
                                            <div className="space-y-0.5 ml-6">
                                                {properties.map((property) => (
                                                    <PropertyRow key={property.key} property={property} />
                                                ))}
                                            </div>
                                        </div>
                                    )
                                }

                                return (
                                    <>
                                        {renderSection(
                                            'Current',
                                            <IconPerson className="w-4 h-4" />,
                                            currentProperties
                                        )}
                                        {renderSection(
                                            'Acquisition',
                                            <IconFlag className="w-4 h-4" />,
                                            acquisitionProperties
                                        )}
                                    </>
                                )
                            })()}
                        </LemonCard>
                    )}
                </div>

                {/* Activity Calendar Heatmap */}
                <div className="lg:col-span-7">
                    <div className="flex items-center gap-2 mb-3">
                        <IconPulse className="text-lg" />
                        <h3 className="font-semibold">Activity Calendar</h3>
                        <span className="text-xs text-muted">(Last 7 days)</span>
                    </div>

                    <Query
                        query={
                            {
                                kind: NodeKind.CalendarHeatmapQuery,
                                series: [
                                    {
                                        kind: NodeKind.EventsNode,
                                        name: 'All Events',
                                        event: null,
                                        math: 'total',
                                    },
                                ],
                                properties: [
                                    {
                                        key: `distinct_id IN (${person.distinct_ids?.map((id) => `'${id}'`).join(', ') || "''"})`,
                                        value: 'true',
                                        type: PropertyFilterType.HogQL,
                                    },
                                ],
                                dateRange: {
                                    date_from: '-12m',
                                    date_to: null,
                                },
                                interval: 'month',
                                calendarHeatmapFilter: {},
                            } as CalendarHeatmapQuery
                        }
                        context={{
                            emptyStateHeading: 'No activity data',
                            emptyStateDetail: 'This person has no recorded activity in the last 7 days.',
                            insightProps: {
                                dashboardItemId: `new-person-summary-${person.uuid || 'unknown'}` as const,
                            },
                        }}
                    />
                </div>
            </div>

            {/* View All Properties Link */}
            <div className="text-center pt-2">
                <p className="text-xs text-muted">
                    Want to see all properties? Check out the <strong>Properties</strong> tab for the complete list.
                </p>
            </div>
        </div>
    )
}
