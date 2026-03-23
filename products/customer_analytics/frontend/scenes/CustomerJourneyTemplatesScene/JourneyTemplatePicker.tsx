import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconPlus, IconTarget, IconTrending } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, Link } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { InsightIcon } from 'scenes/saved-insights/SavedInsights'
import { urls } from 'scenes/urls'

import { QueryBasedInsightModel } from '~/types'

import { JourneyTemplateKey, journeyTemplatePickerLogic } from './journeyTemplatePickerLogic'

interface TemplateCardConfig {
    key: JourneyTemplateKey
    title: string
    description: string
    icon: React.ComponentType<{ className?: string }>
    available: boolean
    disabledReason?: string
}

function TemplateCard({ config, onClick }: { config: TemplateCardConfig; onClick: () => void }): JSX.Element {
    const Icon = config.icon
    const card = (
        <button
            type="button"
            data-attr={`journey-template-card-${config.key}`}
            onClick={config.available ? onClick : undefined}
            disabled={!config.available}
            className={clsx(
                'group relative text-left rounded-lg border border-border bg-bg-light transition-all p-5 w-full',
                config.available
                    ? 'hover:border-border-bold hover:shadow-sm cursor-pointer focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2'
                    : 'opacity-50 cursor-not-allowed'
            )}
        >
            <div className="flex flex-col gap-3">
                <Icon className={clsx('text-2xl transition-colors', config.available && 'group-hover:text-link')} />
                <div>
                    <h3
                        className={clsx(
                            'font-semibold text-base mb-1 transition-colors',
                            config.available && 'group-hover:text-link'
                        )}
                    >
                        {config.title}
                    </h3>
                    <p className="text-sm text-muted m-0">{config.description}</p>
                </div>
            </div>
        </button>
    )

    if (!config.available && config.disabledReason) {
        return (
            <Tooltip title={config.disabledReason}>
                <div>{card}</div>
            </Tooltip>
        )
    }
    return card
}

export function JourneyTemplatePicker(): JSX.Element {
    const {
        isSignupConversionAvailable,
        isFreeToPaidAvailable,
        showExistingFunnels,
        funnels,
        funnelsLoading,
        searchTerm,
    } = useValues(journeyTemplatePickerLogic)
    const { selectTemplate, selectExistingFunnel, toggleExistingFunnels, setSearchTerm } =
        useActions(journeyTemplatePickerLogic)
    const summarizeInsight = useSummarizeInsight()
    const funnelsSectionRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (showExistingFunnels && funnelsSectionRef.current) {
            funnelsSectionRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
        }
    }, [showExistingFunnels])

    const templates: TemplateCardConfig[] = [
        {
            key: 'signup_conversion',
            title: 'Signup conversion',
            description: 'Track how users convert from viewing your signup page to completing signup',
            icon: IconTrending,
            available: isSignupConversionAvailable,
            disabledReason: `Configure signup pageview and signup events in Customer analytics settings to use this template`,
        },
        {
            key: 'free_to_paid',
            title: 'Free-to-paid conversion',
            description: 'Track how users convert from signing up to making their first payment',
            icon: IconTarget,
            available: isFreeToPaidAvailable,
            disabledReason: `Configure signup and payment events in Customer analytics settings to use this template`,
        },
        {
            key: 'scratch',
            title: 'Start from scratch',
            description: 'Build a custom journey funnel from any events',
            icon: IconPlus,
            available: true,
        },
    ]

    return (
        <div className="space-y-6">
            <div className="text-center max-w-xl mx-auto">
                <h2 className="text-2xl font-semibold mb-4">Create a customer journey</h2>
                <p className="text-muted text-sm">
                    Choose a template to get started quickly, or build a custom journey from scratch.
                    {(!isSignupConversionAvailable || !isFreeToPaidAvailable) && (
                        <>
                            {' '}
                            <Link to={urls.customerAnalyticsConfiguration()}>Configure events</Link> to unlock more
                            templates.
                        </>
                    )}
                </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {templates.map((template) => (
                    <TemplateCard key={template.key} config={template} onClick={() => selectTemplate(template.key)} />
                ))}
            </div>

            <LemonDivider />

            <div ref={funnelsSectionRef}>
                <span className="flex justify-center items-center">
                    <LemonButton type="tertiary" onClick={toggleExistingFunnels}>
                        {showExistingFunnels ? 'Hide existing funnels' : 'Start from an existing funnel'}
                    </LemonButton>
                </span>

                {showExistingFunnels && (
                    <div className="mt-4 space-y-3">
                        <LemonInput
                            type="search"
                            placeholder="Search funnels..."
                            value={searchTerm}
                            onChange={(value) => setSearchTerm(value)}
                            autoFocus
                        />
                        <LemonTable
                            dataSource={funnels}
                            columns={[
                                {
                                    key: 'id',
                                    width: 32,
                                    render: function renderType(_, insight) {
                                        return <InsightIcon insight={insight} className="text-secondary text-2xl" />
                                    },
                                },
                                {
                                    title: 'Name',
                                    dataIndex: 'name',
                                    key: 'name',
                                    render: function renderName(name: string, insight) {
                                        const displayName = name || summarizeInsight(insight.query)
                                        return (
                                            <div className="flex flex-col gap-1 min-w-0">
                                                <span className="block truncate">{name || <i>{displayName}</i>}</span>
                                                {insight.description && (
                                                    <div className="text-xs text-tertiary truncate">
                                                        {insight.description}
                                                    </div>
                                                )}
                                            </div>
                                        )
                                    },
                                },
                                {
                                    title: 'Tags',
                                    dataIndex: 'tags' as keyof QueryBasedInsightModel,
                                    key: 'tags',
                                    render: function renderTags(tags: string[]) {
                                        return <ObjectTags tags={tags} staticOnly />
                                    },
                                },
                                {
                                    title: 'Last modified',
                                    dataIndex: 'last_modified_at',
                                    render: function renderLastModified(last_modified_at: string) {
                                        return (
                                            <div className="whitespace-nowrap">
                                                {last_modified_at && <TZLabel time={last_modified_at} />}
                                            </div>
                                        )
                                    },
                                },
                            ]}
                            loading={funnelsLoading}
                            rowKey="id"
                            nouns={['funnel', 'funnels']}
                            rowClassName="cursor-pointer hover:bg-primary-highlight/30"
                            onRow={(insight) => ({
                                onClick: () => selectExistingFunnel(insight.id),
                            })}
                            emptyState={
                                searchTerm ? (
                                    <div className="text-muted text-center p-4">
                                        No funnels found matching your search
                                    </div>
                                ) : (
                                    <div className="text-muted text-center p-4">No saved funnel insights found</div>
                                )
                            }
                        />
                    </div>
                )}
            </div>
        </div>
    )
}
