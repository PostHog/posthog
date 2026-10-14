import type React from 'react'

import type { IntegrationKind, IntegrationType } from '~/types'

import type { ExternalDataDestinationTypeEnumApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

/** The PostHog warehouse is managed by the sync itself, so it is not creatable. */
export type CreatableDestinationType = Exclude<ExternalDataDestinationTypeEnumApi, 'PostHogWarehouse'>

export interface DestinationContext {
    isNew: boolean
    formValues: Record<string, any>
    selectedIntegration?: IntegrationType | null
}

export interface WarehouseDestinationDefinition {
    type: CreatableDestinationType
    /** S3 names two, so the modal asks which provider before listing connections. */
    integrationKinds: IntegrationKind[]
    defaults: () => Record<string, any>
    requiredFields: (ctx: DestinationContext) => string[]
    validate?: (formValues: Record<string, any>) => Record<string, string | undefined>
    /**
     * Mirrors what this type's writer reads in `pipeline_v3/destinations_load/writers/`.
     * `buildDestinationConfig` drops everything else, so switching type in the form cannot
     * carry another type's fields into the payload.
     */
    configKeys: string[]
    /**
     * Config that pins where already-synced rows live. The backend refuses to change these
     * after creation; mirrors `RETARGETING_FIELDS_BY_TYPE` in the destination serializer.
     */
    retargetingKeys: string[]
    serialize?: (formValues: Record<string, any>) => Record<string, any>
    deserialize?: (config: Record<string, any>) => Record<string, any>
    Fields: React.FC<DestinationContext>
}
