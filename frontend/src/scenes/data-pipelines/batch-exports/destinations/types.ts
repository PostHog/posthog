import type React from 'react'

import type { DatabaseSchemaField } from '@posthog/query-frontend/schema/schema-general'

import type { BatchExportService } from '~/types'

export type BatchExportServiceType = BatchExportService['type']

export interface DestinationContext {
    isNew: boolean
    formValues: Record<string, any>
}

// Overrides applied to the events table preview shown in the HogQL model picker.
// `includeGenericPersonFields: false` opts out of the default set/set_once/site_url/ip/elements_chain block.
export interface EventTableOverrides {
    teamIdHogql?: string
    setName?: string
    setOnceName?: string
    includeGenericPersonFields?: boolean
}

export interface DestinationDefinition {
    type: BatchExportServiceType
    defaults: () => Record<string, any>
    requiredFields: (ctx: DestinationContext) => string[]
    // Field-level errors beyond the "required" check. Return undefined for valid fields.
    validate?: (formValues: Record<string, any>) => Record<string, string | undefined>
    // Form fields → API destination.config payload. Default behaviour: pass remaining fields through unchanged.
    serialize?: (formValues: Record<string, any>) => Record<string, any>
    // API destination.config → flat form fields. Default: spread.
    deserialize?: (config: Record<string, any>) => Record<string, any>
    // Extra columns added to the events table preview for this destination.
    eventTableExtraFields?: Record<string, DatabaseSchemaField>
    eventTableOverrides?: EventTableOverrides
    // Lift integration_id from destination.integration during deserialize and push it back during save.
    usesIntegration?: boolean
    Fields: React.FC<{ isNew: boolean; formValues: Record<string, any>; configurationChanged: boolean }>
}
