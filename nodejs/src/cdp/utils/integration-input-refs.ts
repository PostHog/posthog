import { isFeatureFlagEnabled } from '~/common/utils/posthog'

import { IntegrationType } from '../types'

// Persisted job state holds this in place of a resolved integration input, so the job queue never stores the
// decrypted config. The executor loads the integration again from the id before the function runs.
export const INTEGRATION_REF_KEY = '$integration_ref'

export type IntegrationInputRef = { [INTEGRATION_REF_KEY]: IntegrationType['id'] }

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null && !Array.isArray(value)

const isIntegrationId = (value: unknown): value is IntegrationType['id'] =>
    typeof value === 'number' || (typeof value === 'string' && value.length > 0)

export const isIntegrationRef = (value: unknown): value is IntegrationInputRef =>
    isPlainObject(value) && isIntegrationId(value[INTEGRATION_REF_KEY])

export const hasIntegrationRef = (inputs: Record<string, unknown>): boolean =>
    Object.values(inputs).some(
        (value) => isIntegrationRef(value) || (Array.isArray(value) && value.some(isIntegrationRef))
    )

const toRef = (value: unknown): unknown =>
    isPlainObject(value) && isIntegrationId(value.$integration_id)
        ? { [INTEGRATION_REF_KEY]: value.$integration_id }
        : value

/**
 * Replaces each resolved integration input (and each item of an integration_multi input) with a reference.
 * Returns the same object when no input holds a resolved integration.
 */
export function replaceIntegrationInputsWithRefs(inputs: Record<string, any>): Record<string, any> {
    let changed = false
    const result: Record<string, any> = {}
    for (const [key, value] of Object.entries(inputs)) {
        const next = Array.isArray(value) ? value.map(toRef) : toRef(value)
        if (Array.isArray(value) ? (next as unknown[]).some((item, i) => item !== value[i]) : next !== value) {
            changed = true
            result[key] = next
        } else {
            result[key] = value
        }
    }
    return changed ? result : inputs
}

const FLAG_KEY = 'cdp-integration-input-refs'
// The flag gates the whole fleet at once, because a worker that runs older code cannot read a reference.
const FLAG_DISTINCT_ID = 'cdp-cyclotron-job-queue'
const FLAG_TTL_MS = 60_000

/**
 * Reads the rollout flag synchronously, so the enqueue path does not wait on the network.
 * A stale value starts one refresh in the background. Until the first refresh ends, the value is off.
 */
export class IntegrationInputRefsRollout {
    private enabled = false
    private expiresAt = 0
    private refreshing = false

    constructor(private evaluate: () => Promise<boolean> = () => isFeatureFlagEnabled(FLAG_KEY, FLAG_DISTINCT_ID)) {}

    public isEnabled(): boolean {
        if (!this.refreshing && Date.now() >= this.expiresAt) {
            this.refreshing = true
            void this.evaluate()
                .then((enabled) => {
                    this.enabled = enabled
                })
                .catch(() => {
                    this.enabled = false
                })
                .finally(() => {
                    this.expiresAt = Date.now() + FLAG_TTL_MS
                    this.refreshing = false
                })
        }
        return this.enabled
    }
}
