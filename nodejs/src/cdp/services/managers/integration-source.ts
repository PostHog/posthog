import { IntegrationType } from '~/cdp/types'
import { IntegrationReference } from '~/cdp/utils/integration-reference'

/**
 * `undecryptable`: the value is a Fernet token that no configured key opens. The record keeps the
 * token in place of the secret.
 * `nested_ciphertext`: one layer opened, but the result is a Fernet token again.
 */
export type IntegrationDecryptFailureReason = 'undecryptable' | 'nested_ciphertext'

export type IntegrationDecryptFailure = {
    /** Dotted path of the field in `sensitive_config`. Never the value. */
    path: string
    reason: IntegrationDecryptFailureReason
}

export type IntegrationSourceRecord = {
    reference: IntegrationReference
    integration: IntegrationType
    /** Epoch milliseconds. The cache does not serve the record after this time. */
    expiresAt?: number
    /** The fields of `sensitive_config` that did not decrypt. Empty when all fields decrypt. */
    decryptFailures: IntegrationDecryptFailure[]
}

/**
 * Where `IntegrationManagerService` reads integrations from. The `postgres` source reads
 * `posthog_integration`. A `service` source reads the credentials service.
 */
export interface IntegrationSource {
    /** A short label for metrics and logs, for example `postgres`. */
    readonly name: string

    /**
     * Loads a batch of integrations. The result has no entry for a reference that has no row.
     * The references are canonical, and the source must not scope them by team: callers check
     * `team_id` on each record.
     */
    load(references: IntegrationReference[]): Promise<Record<IntegrationReference, IntegrationSourceRecord>>
}
