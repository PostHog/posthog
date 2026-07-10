/**
 * Bridge hook between PostHog's kea logics and the pure `buildTaxonomicGroups`
 * builder. Reads the same connections that `taxonomicFilterLogic.connect`
 * declares, layers in prop-derived defaults, and returns a memoised
 * `BuildTaxonomicGroupsContext` ready to feed into `buildTaxonomicGroups(ctx)`.
 *
 * This is the only kea-coupled layer of the new headless `useTaxonomicFilter`.
 * Everything else operates on the returned plain-object context, so swapping
 * kea for direct API calls later is a single-file change.
 */
import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import {
    AllowedProperties,
    ExcludedProperties,
    SelectedProperties,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import {
    buildGroupAnalyticsTaxonomicGroupNames,
    buildGroupAnalyticsTaxonomicGroups,
} from 'lib/components/TaxonomicFilter/utils/buildGroupAnalyticsGroups'
import { BuildTaxonomicGroupsContext } from 'lib/components/TaxonomicFilter/utils/buildTaxonomicGroups'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getPrimaryPropertyForEvent } from 'lib/utils/events'
import { dataWarehouseSettingsSceneLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsSceneLogic'
import { MaxContextTaxonomicFilterOption } from 'scenes/max/maxTypes'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { primaryEventPropertiesModel } from '~/models/primaryEventPropertiesModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { AnyDataNode, DatabaseSchemaField, NodeKind } from '~/queries/schema/schema-general'

import { joinsLogic } from 'products/data_warehouse/frontend/shared/logics/joinsLogic'

/**
 * Inputs the headless hook needs from its consumer. A subset of
 * `TaxonomicFilterProps` — only the fields that affect group definitions.
 */
export interface UseTaxonomicGroupsContextInput {
    eventNames?: string[]
    /** Requested group types — read by group definitions that adapt to which tabs are present. */
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    schemaColumns?: DatabaseSchemaField[]
    schemaColumnsLoading?: boolean
    metadataSource?: AnyDataNode
    suggestedFiltersLabel?: string
    excludedProperties?: ExcludedProperties
    propertyAllowList?: AllowedProperties
    selectedProperties?: SelectedProperties
    maxContextOptions?: MaxContextTaxonomicFilterOption[]
    hideBehavioralCohorts?: boolean
    endpointFilters?: Record<string, any>
    hogQLGlobals?: Record<string, any>
    hogQLExpressionShowBreakdownLabelHint?: boolean
}

const DEFAULT_METADATA_SOURCE: AnyDataNode = {
    kind: NodeKind.HogQLQuery,
    query: 'select event from events',
}

const EMPTY_OBJECT = Object.freeze({}) as Record<string, never>
const EMPTY_ARRAY: readonly never[] = Object.freeze([])

export function useTaxonomicGroupsContext(input: UseTaxonomicGroupsContextInput): BuildTaxonomicGroupsContext {
    const { currentTeam } = useValues(teamLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { groupTypes, aggregationLabel } = useValues(groupsModel)
    // Mounted purely so the dataWarehouse popover doesn't error out when the
    // logic isn't otherwise on the page — same reason taxonomicFilterLogic
    // does it.
    useValues(dataWarehouseSettingsSceneLogic)
    useValues(joinsLogic)
    const { eventMetadataPropertyDefinitions, personMetadataPropertyDefinitions } = useValues(propertyDefinitionsModel)
    const { featureFlags } = useValues(featureFlagLogic)
    const { primaryProperties } = useValues(primaryEventPropertiesModel)
    const { ensureLoadedForEvents } = useActions(primaryEventPropertiesModel)

    // Mirrors taxonomicFilterLogic's afterMount/propsChanged: fetch any
    // team-configured primary-property overrides for the events in context.
    // Content-keyed like the ctx memo below — consumers pass fresh array
    // literals per render, and ensureLoadedForEvents shouldn't refire for a
    // referentially-new-but-equal list.
    const eventNames = input.eventNames
    const eventNamesKey = JSON.stringify(eventNames ?? [])
    useEffect(() => {
        if (eventNames?.length) {
            ensureLoadedForEvents(eventNames)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [eventNamesKey, ensureLoadedForEvents])

    // Mirrors the `eventNamesWithPrimaryProperties` selector in
    // taxonomicFilterLogic: the distinct promoted properties for the events in
    // context (taxonomy default first, then team override).
    const promotedPropertiesForContextEvents = useMemo(() => {
        const distinct = new Set<string>()
        for (const eventName of eventNames ?? []) {
            const primary = getPrimaryPropertyForEvent(eventName, primaryProperties)
            if (primary) {
                distinct.add(primary)
            }
        }
        return Array.from(distinct)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [eventNamesKey, primaryProperties])

    return useMemo<BuildTaxonomicGroupsContext>(() => {
        const propertyFilters = {
            excludedProperties: (input.excludedProperties ?? EMPTY_OBJECT) as Record<
                TaxonomicFilterGroupType,
                (string | number | null)[]
            >,
            propertyAllowList: input.propertyAllowList as
                | Record<TaxonomicFilterGroupType, (string | number | null)[]>
                | undefined,
        }
        const hogQLExpressionComponentProps = {
            globals: input.hogQLGlobals,
            showBreakdownLabelHint: input.hogQLExpressionShowBreakdownLabelHint ?? false,
        }
        return {
            // `BuildTaxonomicGroupsContext.currentTeam` is non-nullable; the
            // logic-backed value is nullable until the team boots. Cast
            // through `unknown` — the consuming `buildTaxonomicGroups`
            // path tolerates a missing team for the early-mount frame.
            currentTeam: currentTeam as unknown as BuildTaxonomicGroupsContext['currentTeam'],
            projectId: currentProjectId,
            groupAnalyticsTaxonomicGroups: buildGroupAnalyticsTaxonomicGroups(
                groupTypes,
                currentProjectId,
                aggregationLabel
            ),
            groupAnalyticsTaxonomicGroupNames: buildGroupAnalyticsTaxonomicGroupNames(
                groupTypes,
                currentTeam?.id ?? 0,
                aggregationLabel
            ),
            eventNames: input.eventNames ?? (EMPTY_ARRAY as unknown as string[]),
            taxonomicGroupTypes: input.taxonomicGroupTypes,
            promotedPropertiesForContextEvents,
            schemaColumns: input.schemaColumns ?? (EMPTY_ARRAY as unknown as DatabaseSchemaField[]),
            schemaColumnsLoading: input.schemaColumnsLoading,
            metadataSource: input.metadataSource ?? DEFAULT_METADATA_SOURCE,
            suggestedFiltersLabel: input.suggestedFiltersLabel,
            propertyFilters,
            eventMetadataPropertyDefinitions,
            personMetadataPropertyDefinitions,
            maxContextOptions: input.maxContextOptions ?? (EMPTY_ARRAY as unknown as MaxContextTaxonomicFilterOption[]),
            hideBehavioralCohorts: input.hideBehavioralCohorts ?? false,
            endpointFilters: input.endpointFilters,
            hogQLExpressionComponentProps,
            // `featureFlags` from featureFlagLogic returns the project's
            // own `FeatureFlagsSet` shape; widen to the looser
            // `Record<string, boolean | string | undefined>` the
            // taxonomic-groups builder accepts.
            featureFlags: featureFlags as unknown as BuildTaxonomicGroupsContext['featureFlags'],
        }
    }, [
        currentTeam,
        currentProjectId,
        groupTypes,
        aggregationLabel,
        eventMetadataPropertyDefinitions,
        personMetadataPropertyDefinitions,
        featureFlags,
        promotedPropertiesForContextEvents,
        // Content-keyed: consumers pass fresh array literals per render. The legacy logic
        // stabilizes the same props differently — reference-equality inputs with objectsEqual
        // on the selector result (see eventNamesWithPrimaryProperties) — same end effect.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        JSON.stringify(input.eventNames),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        JSON.stringify(input.taxonomicGroupTypes),
        input.schemaColumns,
        input.schemaColumnsLoading,
        input.metadataSource,
        input.suggestedFiltersLabel,
        input.excludedProperties,
        input.propertyAllowList,
        input.maxContextOptions,
        input.hideBehavioralCohorts,
        input.endpointFilters,
        input.hogQLGlobals,
        input.hogQLExpressionShowBreakdownLabelHint,
    ])
}
