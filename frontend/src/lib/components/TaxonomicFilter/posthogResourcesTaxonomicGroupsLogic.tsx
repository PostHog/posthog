import clsx from 'clsx'
import { connect, kea, key, path, props, selectors } from 'kea'
import { combineUrl } from 'kea-router'

import { IconFlag } from '@posthog/icons'

import {
    ExcludedProperties,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { isString } from 'lib/utils'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { NotebookType } from 'scenes/notebooks/types'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardType, Experiment, FeatureFlagType, QueryBasedInsightModel } from '~/types'

import type { posthogResourcesTaxonomicGroupsLogicType } from './posthogResourcesTaxonomicGroupsLogicType'

export const posthogResourcesTaxonomicGroupsLogic = kea<posthogResourcesTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'posthogResourcesTaxonomicGroupsLogic', key]),

    connect(() => ({
        values: [teamLogic, ['currentTeam'], projectLogic, ['currentProjectId']],
    })),

    selectors({
        excludedProperties: [
            () => [(_, props) => props.excludedProperties],
            (excludedProperties) => (excludedProperties ?? {}) as ExcludedProperties,
        ],
        posthogResourcesTaxonomicGroups: [
            (s) => [s.currentTeam, s.currentProjectId, s.excludedProperties],
            (currentTeam, projectId, excludedProperties): TaxonomicFilterGroup[] => {
                const teamId = currentTeam?.id
                return [
                    {
                        name: 'Insights',
                        searchPlaceholder: 'insights',
                        type: TaxonomicFilterGroupType.Insights,
                        endpoint: combineUrl(`api/environments/${teamId}/insights/`, {
                            saved: true,
                        }).url,
                        getName: (insight: QueryBasedInsightModel) => insight.name,
                        getValue: (insight: QueryBasedInsightModel) => insight.short_id,
                        getPopoverHeader: () => `Insights`,
                    },
                    {
                        name: 'Feature Flags',
                        searchPlaceholder: 'feature flags',
                        type: TaxonomicFilterGroupType.FeatureFlags, // Feature flag dependencies
                        endpoint: combineUrl(`api/projects/${projectId}/feature_flags/`).url,
                        getName: (featureFlag: FeatureFlagType) => {
                            const name = featureFlag.key || featureFlag.name
                            const isInactive = !featureFlag.active
                            return isInactive ? `${name} (disabled)` : name
                        },
                        getValue: (featureFlag: FeatureFlagType) => featureFlag.id || '',
                        getPopoverHeader: () => `Feature Flags`,
                        getIcon: (featureFlag: FeatureFlagType) => (
                            <IconFlag className={clsx('size-4', !featureFlag.active && 'text-muted-alt opacity-50')} />
                        ),
                        getIsDisabled: (featureFlag: FeatureFlagType) => !featureFlag.active,
                        localItemsSearch: (
                            items: TaxonomicDefinitionTypes[],
                            query: string
                        ): TaxonomicDefinitionTypes[] => {
                            if (!query) {
                                return items
                            }
                            return items.filter((item) => {
                                const flag = item as unknown as FeatureFlagType
                                return (flag.key || flag.name || '').toLowerCase().includes(query.toLowerCase())
                            })
                        },
                        excludedProperties:
                            excludedProperties?.[TaxonomicFilterGroupType.FeatureFlags]?.filter(isString),
                    },
                    {
                        name: 'Experiments',
                        searchPlaceholder: 'experiments',
                        type: TaxonomicFilterGroupType.Experiments,
                        logic: experimentsLogic,
                        value: 'experiments',
                        getName: (experiment: Experiment) => experiment.name,
                        getValue: (experiment: Experiment) => experiment.id,
                        getPopoverHeader: () => `Experiments`,
                    },
                    {
                        name: 'Dashboards',
                        searchPlaceholder: 'dashboards',
                        type: TaxonomicFilterGroupType.Dashboards,
                        logic: dashboardsModel,
                        value: 'nameSortedDashboards',
                        getName: (dashboard: DashboardType) => dashboard.name,
                        getValue: (dashboard: DashboardType) => dashboard.id,
                        getPopoverHeader: () => `Dashboards`,
                    },
                    {
                        name: 'Notebooks',
                        searchPlaceholder: 'notebooks',
                        type: TaxonomicFilterGroupType.Notebooks,
                        value: 'notebooks',
                        endpoint: `api/projects/${projectId}/notebooks/`,
                        getName: (notebook: NotebookType) => notebook.title || `Notebook ${notebook.short_id}`,
                        getValue: (notebook: NotebookType) => notebook.short_id,
                        getPopoverHeader: () => 'Notebooks',
                    },
                ]
            },
        ],
    }),
])
