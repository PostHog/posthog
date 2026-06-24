/** Auto-generated from products/dashboards/backend/widget_specs — do not edit.
 * Regenerate: hogli build:widget-types
 */
import { z as zod } from 'zod'

import { ActivityEventsListWidgetConfig } from './widget-config-schemas/activityEventsListWidgetConfig.zod'
import { ErrorTrackingListWidgetConfig } from './widget-config-schemas/errorTrackingListWidgetConfig.zod'
import { ExperimentResultsWidgetConfig as ExperimentResultsWidgetConfigComponent } from './widget-config-schemas/experimentResultsWidgetConfig.zod'
import { ExperimentsListWidgetConfig } from './widget-config-schemas/experimentsListWidgetConfig.zod'
import { LlmAnalyticsTracesListWidgetConfig } from './widget-config-schemas/llmAnalyticsTracesListWidgetConfig.zod'
import { SessionReplayListWidgetConfig } from './widget-config-schemas/sessionReplayListWidgetConfig.zod'
import { WidgetFilterEntry } from './widget-config-schemas/widgetFilterEntry.zod'

export const activityEventsWidgetConfigSchema = /* @__PURE__ */ ActivityEventsListWidgetConfig
export const errorTrackingWidgetConfigSchema = /* @__PURE__ */ ErrorTrackingListWidgetConfig
export const experimentResultsWidgetConfigSchema = /* @__PURE__ */ ExperimentResultsWidgetConfigComponent
export const experimentsWidgetConfigSchema = /* @__PURE__ */ ExperimentsListWidgetConfig
export const llmAnalyticsTracesWidgetConfigSchema = /* @__PURE__ */ LlmAnalyticsTracesListWidgetConfig
export const sessionReplayWidgetConfigSchema = /* @__PURE__ */ SessionReplayListWidgetConfig
export const widgetFilterEntrySchema = /* @__PURE__ */ WidgetFilterEntry

export type ActivityEventsWidgetConfig = zod.infer<typeof activityEventsWidgetConfigSchema>
export type ErrorTrackingWidgetConfig = zod.infer<typeof errorTrackingWidgetConfigSchema>
export type ExperimentResultsWidgetConfig = zod.infer<typeof experimentResultsWidgetConfigSchema>
export type ExperimentsWidgetConfig = zod.infer<typeof experimentsWidgetConfigSchema>
export type LlmAnalyticsTracesWidgetConfig = zod.infer<typeof llmAnalyticsTracesWidgetConfigSchema>
export type SessionReplayWidgetConfig = zod.infer<typeof sessionReplayWidgetConfigSchema>

type WidgetFiltersRecord = NonNullable<ActivityEventsWidgetConfig['widgetFilters']>
export type WidgetFilterConfigEntry = WidgetFiltersRecord[string]
export type WidgetFilterConfigRecord = WidgetFiltersRecord
export type StoredWidgetFilter = WidgetFilterConfigEntry

export const activityEventsWidgetFormSchema = activityEventsWidgetConfigSchema.pick({
    limit: true,
    dateRange: true,
    filterTestAccounts: true,
})

export const errorTrackingWidgetFormSchema = errorTrackingWidgetConfigSchema.pick({
    limit: true,
    orderBy: true,
    orderDirection: true,
    dateRange: true,
    filterTestAccounts: true,
    status: true,
})

export const experimentResultsWidgetFormSchema = experimentResultsWidgetConfigSchema.pick({
    experimentId: true,
})

export const experimentsWidgetFormSchema = experimentsWidgetConfigSchema.pick({
    limit: true,
    orderBy: true,
    orderDirection: true,
    status: true,
    createdBy: true,
})

export const llmAnalyticsTracesWidgetFormSchema = llmAnalyticsTracesWidgetConfigSchema.pick({
    limit: true,
    dateRange: true,
    filterTestAccounts: true,
    filterSupportTraces: true,
})

export const sessionReplayWidgetFormSchema = sessionReplayWidgetConfigSchema.pick({
    limit: true,
    orderBy: true,
    orderDirection: true,
    dateRange: true,
    filterTestAccounts: true,
})
