import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { TagSelect } from 'lib/components/TagSelect'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'

import { FeatureFlagEvaluationRuntime } from '~/types'

import { FeatureFlagsFilters } from './featureFlagsLogic'

export interface FeatureFlagFiltersConfig {
    search?: boolean
    type?: boolean
    status?: boolean
    createdBy?: boolean
    runtime?: boolean
    tags?: boolean
}

interface FeatureFlagFiltersProps {
    filters: FeatureFlagsFilters
    setFeatureFlagsFilters: (filters: Partial<FeatureFlagsFilters>, replace?: boolean) => void
    searchPlaceholder?: string
    filtersConfig?: FeatureFlagFiltersConfig
}

export function FeatureFlagFiltersSection({
    filters,
    setFeatureFlagsFilters,
    searchPlaceholder = 'Search for feature flags',
    filtersConfig = {},
}: FeatureFlagFiltersProps): JSX.Element {
    const config = {
        search: false,
        type: false,
        status: false,
        createdBy: false,
        runtime: false,
        tags: false,
        ...filtersConfig,
    }
    const hasNonSearchFilters = config.type || config.status || config.createdBy || config.runtime || config.tags

    return (
        <div className="flex justify-between gap-2 flex-wrap">
            {config.search && (
                <LemonInput
                    className="w-60"
                    type="search"
                    placeholder={searchPlaceholder}
                    onChange={(search) => setFeatureFlagsFilters({ search, page: 1 })}
                    value={filters.search || ''}
                    data-attr="feature-flag-search"
                />
            )}
            {hasNonSearchFilters && (
                <div className="flex items-center gap-2">
                    {config.type && (
                        <>
                            <span>
                                <b>Type</b>
                            </span>
                            <LemonSelect
                                dropdownMatchSelectWidth={false}
                                size="small"
                                onChange={(type) => {
                                    if (type) {
                                        if (type === 'all') {
                                            if (filters) {
                                                const { type, ...restFilters } = filters
                                                setFeatureFlagsFilters({ ...restFilters, page: 1 }, true)
                                            }
                                        } else {
                                            setFeatureFlagsFilters({ type, page: 1 })
                                        }
                                    }
                                }}
                                options={[
                                    { label: 'All', value: 'all' },
                                    { label: 'Boolean', value: 'boolean' },
                                    {
                                        label: 'Multiple variants',
                                        value: 'multivariant',
                                        'data-attr': 'feature-flag-select-type-option-multiple-variants',
                                    },
                                    { label: 'Experiment', value: 'experiment' },
                                    { label: 'Remote config', value: 'remote_config' },
                                ]}
                                value={filters.type ?? 'all'}
                                data-attr="feature-flag-select-type"
                            />
                        </>
                    )}
                    {config.status && (
                        <>
                            <span>
                                <b>Status</b>
                            </span>
                            <LemonSelect
                                dropdownMatchSelectWidth={false}
                                size="small"
                                onChange={(status) => {
                                    const { active, ...restFilters } = filters || {}
                                    if (status === 'all') {
                                        setFeatureFlagsFilters({ ...restFilters, page: 1 }, true)
                                    } else if (status === 'STALE') {
                                        setFeatureFlagsFilters({ ...restFilters, active: 'STALE', page: 1 }, true)
                                    } else {
                                        setFeatureFlagsFilters({ ...restFilters, active: status, page: 1 }, true)
                                    }
                                }}
                                options={[
                                    { label: 'All', value: 'all', 'data-attr': 'feature-flag-select-status-all' },
                                    { label: 'Enabled', value: 'true' },
                                    {
                                        label: 'Disabled',
                                        value: 'false',
                                        'data-attr': 'feature-flag-select-status-disabled',
                                    },
                                    {
                                        label: 'Stale',
                                        value: 'STALE',
                                        'data-attr': 'feature-flag-select-status-stale',
                                    },
                                ]}
                                value={filters.active ?? 'all'}
                                data-attr="feature-flag-select-status"
                            />
                        </>
                    )}
                    {config.createdBy && (
                        <>
                            <span className="ml-1">
                                <b>Created by</b>
                            </span>
                            <MemberSelect
                                defaultLabel="Any user"
                                value={filters.created_by_id ?? null}
                                onChange={(user) => {
                                    if (!user) {
                                        if (filters) {
                                            const { created_by_id, ...restFilters } = filters
                                            setFeatureFlagsFilters({ ...restFilters, page: 1 }, true)
                                        }
                                    } else {
                                        setFeatureFlagsFilters({ created_by_id: user.id, page: 1 })
                                    }
                                }}
                                data-attr="feature-flag-select-created-by"
                            />
                        </>
                    )}
                    {config.tags && enabledFeaturesLogic.values.featureFlags?.[FEATURE_FLAGS.FLAG_EVALUATION_TAGS] && (
                        <>
                            <span className="ml-1">
                                <b>Tags</b>
                            </span>
                            <TagSelect
                                defaultLabel="Any tags"
                                value={filters.tags || []}
                                onChange={(tags) => {
                                    setFeatureFlagsFilters({ tags: tags.length > 0 ? tags : undefined, page: 1 })
                                }}
                                data-attr="feature-flag-select-tags"
                            />
                        </>
                    )}
                    {config.runtime &&
                        enabledFeaturesLogic.values.featureFlags?.[FEATURE_FLAGS.FLAG_EVALUATION_RUNTIMES] && (
                            <>
                                <span className="ml-1">
                                    <b>Runtime</b>
                                </span>
                                <LemonSelect
                                    dropdownMatchSelectWidth={false}
                                    size="small"
                                    onChange={(runtime) => {
                                        const { evaluation_runtime, ...restFilters } = filters || {}
                                        if (runtime === 'any') {
                                            setFeatureFlagsFilters({ ...restFilters, page: 1 }, true)
                                        } else {
                                            setFeatureFlagsFilters(
                                                { ...restFilters, evaluation_runtime: runtime, page: 1 },
                                                true
                                            )
                                        }
                                    }}
                                    options={[
                                        { label: 'Any', value: 'any', 'data-attr': 'feature-flag-select-runtime-any' },
                                        { label: 'All', value: FeatureFlagEvaluationRuntime.ALL },
                                        { label: 'Client', value: FeatureFlagEvaluationRuntime.CLIENT },
                                        { label: 'Server', value: FeatureFlagEvaluationRuntime.SERVER },
                                    ]}
                                    value={filters.evaluation_runtime ?? 'any'}
                                    data-attr="feature-flag-select-runtime"
                                />
                            </>
                        )}
                </div>
            )}
        </div>
    )
}
