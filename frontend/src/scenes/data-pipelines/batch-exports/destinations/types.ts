import type React from 'react'

import type { DatabaseSchemaField } from '~/queries/schema/schema-general'
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
    // Allowlist of valid destination.config keys (mirrors the backend workflow-inputs dataclass in
    // products/batch_exports/backend/service.py, destination-specific fields only). When set,
    // buildDestinationPayload drops any other key — guards against stale/legacy fields being
    // re-sent and rejected by the backend. Omit to keep pass-through behaviour.
    // TODO: ideally we could get this from the backend
    configKeys?: string[]
    // API destination.config → flat form fields. Default: spread.
    deserialize?: (config: Record<string, any>) => Record<string, any>
    // Extra columns added to the events table preview for this destination.
    eventTableExtraFields?: Record<string, DatabaseSchemaField>
    eventTableOverrides?: EventTableOverrides
    // Lift integration_id from destination.integration during deserialize and push it back during save.
    usesIntegration?: boolean
    Fields: React.FC<{ isNew: boolean; formValues: Record<string, any> }>
}
