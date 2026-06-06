import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { HogQLQueryModifiers, NodeKind } from '~/queries/schema/schema-general'

import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'

const POSTHOG_WAREHOUSE = '__posthog_warehouse__'

interface QueryWithModifiers {
    connectionId?: string
    kind?: string
    response?: Record<string, any>
    modifiers?: HogQLQueryModifiers
}

export interface ModifiersProps<Q extends QueryWithModifiers> {
    setQuery: (query: Q) => void
    query: Q | null
    response: Required<Q>['response'] | null
}

function ConnectionIdModifier<Q extends QueryWithModifiers>({
    labelClassName,
    query,
    setQuery,
}: {
    labelClassName: string
    query: Q
    setQuery: (query: Q) => void
}): JSX.Element | null {
    const { dataWarehouseSources, dataWarehouseSourcesLoading } = useValues(sourcesDataLogic)
    const { loadSources } = useActions(sourcesDataLogic)
    const isHogQLQuery = query.kind === NodeKind.HogQLQuery

    useEffect(() => {
        if (isHogQLQuery && !dataWarehouseSources) {
            loadSources()
        }
    }, [dataWarehouseSources, isHogQLQuery, loadSources])

    const directPostgresSources = useMemo(
        () =>
            (dataWarehouseSources?.results ?? []).filter(
                (source) => source.access_method === 'direct' && source.source_type.toLowerCase().includes('postgres')
            ),
        [dataWarehouseSources]
    )

    if (!isHogQLQuery) {
        return null
    }

    const selectedValue = query.connectionId ?? POSTHOG_WAREHOUSE
    const hasSelectedConnection =
        !!query.connectionId && directPostgresSources.some((source) => source.id === query.connectionId)

    return (
        <LemonLabel className={labelClassName}>
            <div>Connection ID:</div>
            <LemonSelect
                disabled={dataWarehouseSourcesLoading}
                disabledReason={dataWarehouseSourcesLoading ? 'Loading connections...' : undefined}
                fullWidth
                options={[
                    { value: POSTHOG_WAREHOUSE, label: 'PostHog (ClickHouse)' },
                    ...directPostgresSources.map((source) => ({
                        value: source.id,
                        label: `${source.prefix ?? source.id} (Postgres)`,
                    })),
                    ...(!hasSelectedConnection && query.connectionId
                        ? [{ value: query.connectionId, label: `${query.connectionId} (Unavailable)` }]
                        : []),
                ]}
                onChange={(value) =>
                    setQuery({
                        ...query,
                        connectionId: value === POSTHOG_WAREHOUSE ? undefined : value,
                    })
                }
                value={selectedValue}
            />
        </LemonLabel>
    )
}

export function Modifiers<Q extends QueryWithModifiers>({
    setQuery,
    query,
    response = null,
}: ModifiersProps<Q>): JSX.Element | null {
    if (query === null) {
        return null
    }
    const labelClassName = 'flex min-w-44 flex-1 flex-col items-start gap-1'

    return (
        <div className="deprecated-space-y-2">
            <div className="flex flex-wrap gap-2">
                <ConnectionIdModifier labelClassName={labelClassName} query={query} setQuery={setQuery} />
                <LemonLabel className={labelClassName}>
                    <div>POE:</div>
                    <LemonSelect
                        fullWidth
                        options={[
                            { value: 'disabled', label: 'Disabled' },
                            {
                                value: 'person_id_no_override_properties_on_events',
                                label: 'Properties: Events, Person ID: Events',
                            },
                            {
                                value: 'person_id_override_properties_on_events',
                                label: 'Properties: Events, Person ID: Overrides (v2)',
                            },
                            {
                                value: 'person_id_override_properties_joined',
                                label: 'Properties: Person, Person ID: Overrides (v3)',
                            },
                        ]}
                        onChange={(value) =>
                            setQuery({
                                ...query,
                                modifiers: { ...query.modifiers, personsOnEventsMode: value },
                            })
                        }
                        value={query.modifiers?.personsOnEventsMode ?? response?.modifiers?.personsOnEventsMode}
                    />
                </LemonLabel>
                <LemonLabel className={labelClassName}>
                    <div>Persons ArgMax:</div>
                    <LemonSelect
                        fullWidth
                        options={[
                            { value: 'v1', label: 'V1' },
                            { value: 'v2', label: 'V2' },
                        ]}
                        onChange={(value) =>
                            setQuery({
                                ...query,
                                modifiers: { ...query.modifiers, personsArgMaxVersion: value },
                            })
                        }
                        value={query.modifiers?.personsArgMaxVersion ?? response?.modifiers?.personsArgMaxVersion}
                    />
                </LemonLabel>
                <LemonLabel className={labelClassName}>
                    <div>In Cohort Via:</div>
                    <LemonSelect
                        fullWidth
                        options={[
                            { value: 'auto', label: 'auto' },
                            { value: 'leftjoin', label: 'leftjoin' },
                            { value: 'subquery', label: 'subquery' },
                            { value: 'leftjoin_conjoined', label: 'leftjoin conjoined' },
                        ]}
                        onChange={(value) =>
                            setQuery({
                                ...query,
                                modifiers: { ...query.modifiers, inCohortVia: value },
                            })
                        }
                        value={query.modifiers?.inCohortVia ?? response?.modifiers?.inCohortVia}
                    />
                </LemonLabel>
                <LemonLabel className={labelClassName}>
                    <div>Materialization Mode:</div>
                    <LemonSelect
                        fullWidth
                        options={[
                            { value: 'auto', label: 'auto' },
                            { value: 'legacy_null_as_string', label: 'legacy_null_as_string' },
                            { value: 'legacy_null_as_null', label: 'legacy_null_as_null' },
                            { value: 'disabled', label: 'disabled' },
                        ]}
                        onChange={(value) =>
                            setQuery({
                                ...query,
                                modifiers: { ...query.modifiers, materializationMode: value },
                            })
                        }
                        value={query.modifiers?.materializationMode ?? response?.modifiers?.materializationMode}
                    />
                </LemonLabel>
                <LemonLabel className={labelClassName}>
                    <div>Optimize joined filters:</div>
                    <LemonSelect
                        fullWidth
                        options={[
                            { value: true, label: 'true' },
                            { value: false, label: 'false' },
                        ]}
                        onChange={(value) =>
                            setQuery({
                                ...query,
                                modifiers: { ...query.modifiers, optimizeJoinedFilters: value },
                            })
                        }
                        value={query.modifiers?.optimizeJoinedFilters ?? response?.modifiers?.optimizeJoinedFilters}
                    />
                </LemonLabel>
            </div>
            <div className="flex flex-wrap gap-2">
                <LemonLabel className={labelClassName}>
                    <div>Projection pushdown:</div>
                    <LemonSelect
                        fullWidth
                        options={[
                            { value: true, label: 'true' },
                            { value: false, label: 'false' },
                        ]}
                        onChange={(value) =>
                            setQuery({
                                ...query,
                                modifiers: { ...query.modifiers, optimizeProjections: value },
                            })
                        }
                        value={query.modifiers?.optimizeProjections ?? response?.modifiers?.optimizeProjections}
                    />
                </LemonLabel>
                <LemonLabel className={labelClassName}>
                    <div>Use preaggregated intermediate:</div>
                    <LemonSelect
                        fullWidth
                        options={[
                            { value: true, label: 'true' },
                            { value: false, label: 'false' },
                        ]}
                        onChange={(value) =>
                            setQuery({
                                ...query,
                                modifiers: { ...query.modifiers, usePreaggregatedIntermediateResults: value },
                            })
                        }
                        value={
                            query.modifiers?.usePreaggregatedIntermediateResults ??
                            response?.modifiers?.usePreaggregatedIntermediateResults
                        }
                    />
                </LemonLabel>
                <LemonLabel className={labelClassName}>
                    <div>Property Groups:</div>
                    <LemonSelect
                        fullWidth
                        options={[
                            { value: 'enabled', label: 'Enabled' },
                            { value: 'disabled', label: 'Disabled' },
                            { value: 'optimized', label: 'Enabled, with Optimizations' },
                        ]}
                        onChange={(value) =>
                            setQuery({
                                ...query,
                                modifiers: { ...query.modifiers, propertyGroupsMode: value },
                            })
                        }
                        value={query.modifiers?.propertyGroupsMode ?? response?.modifiers?.propertyGroupsMode}
                    />
                </LemonLabel>
                <LemonLabel className={labelClassName}>
                    <div>Pre-aggregation transformation:</div>
                    <LemonSelect
                        fullWidth
                        options={[
                            { value: true, label: 'true' },
                            { value: false, label: 'false' },
                        ]}
                        onChange={(value) =>
                            setQuery({
                                ...query,
                                modifiers: { ...query.modifiers, usePreaggregatedTableTransforms: value },
                            })
                        }
                        value={
                            query.modifiers?.usePreaggregatedTableTransforms ??
                            response?.modifiers?.usePreaggregatedTableTransforms
                        }
                    />
                </LemonLabel>
                <LemonLabel className={labelClassName}>
                    <div>Session table version:</div>
                    <LemonSelect<Exclude<HogQLQueryModifiers['sessionTableVersion'], undefined>>
                        fullWidth
                        options={[
                            { value: 'auto', label: 'auto' },
                            { value: 'v1', label: 'v1' },
                            { value: 'v2', label: 'v2' },
                            { value: 'v3', label: 'v3' },
                        ]}
                        onChange={(value) =>
                            setQuery({
                                ...query,
                                modifiers: { ...query.modifiers, sessionTableVersion: value },
                            })
                        }
                        value={
                            query.modifiers?.sessionTableVersion ?? response?.modifiers?.sessionTableVersion ?? 'auto'
                        }
                    />
                </LemonLabel>
            </div>
        </div>
    )
}
