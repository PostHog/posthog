/** Auto-generated from products/dashboards/backend/widget_specs — do not edit.
 * Regenerate: hogli build:widget-types
 */
import { z as zod } from 'zod'

import { ErrorTrackingListWidgetConfig } from './widget-config-schemas/errorTrackingListWidgetConfig.zod'
import { SessionReplayListWidgetConfig } from './widget-config-schemas/sessionReplayListWidgetConfig.zod'
import { WidgetFilterEntry } from './widget-config-schemas/widgetFilterEntry.zod'

export const errorTrackingWidgetConfigSchema = /* @__PURE__ */ ErrorTrackingListWidgetConfig
export const sessionReplayWidgetConfigSchema = /* @__PURE__ */ SessionReplayListWidgetConfig
export const widgetFilterEntrySchema = /* @__PURE__ */ WidgetFilterEntry

export type ErrorTrackingWidgetConfig = zod.infer<typeof errorTrackingWidgetConfigSchema>
export type SessionReplayWidgetConfig = zod.infer<typeof sessionReplayWidgetConfigSchema>

type WidgetFiltersRecord = NonNullable<ErrorTrackingWidgetConfig['widgetFilters']>
export type WidgetFilterConfigEntry = WidgetFiltersRecord[string]
export type WidgetFilterConfigRecord = WidgetFiltersRecord
export type StoredWidgetFilter = WidgetFilterConfigEntry

export const errorTrackingWidgetFormSchema = errorTrackingWidgetConfigSchema.pick({
    limit: true,
    orderBy: true,
    orderDirection: true,
    dateRange: true,
    filterTestAccounts: true,
    status: true,
})

export const sessionReplayWidgetFormSchema = sessionReplayWidgetConfigSchema.pick({
    limit: true,
    orderBy: true,
    orderDirection: true,
    dateRange: true,
    filterTestAccounts: true,
})
