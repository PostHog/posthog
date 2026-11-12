import { timingSafeEqual } from 'node:crypto'

import { isFeatureFlagEnabled } from '~/common/utils/posthog'

import { IntegrationType } from '../types'
import type { EncryptedFields } from './encryption-utils'

// Persisted job state holds this in place of a resolved integration input, so the job queue never stores the
// decrypted config. The executor loads the integration again from the id before the function runs.
export const INTEGRATION_REF_KEY = '$integration_ref'
// Event data can hold any JSON, so only a reference that the server signed resolves to an integration.
export const INTEGRATION_REF_SIG_KEY = '$integration_ref_sig'

const INTEGRATION_REF_PURPOSE = 'integration-input-ref'

export type IntegrationInputRef = { [INTEGRATION_REF_KEY]: IntegrationType['id']; [INTEGRATION_REF_SIG_KEY]?: unknown }

export type IntegrationRefSigner = Pick<EncryptedFields, 'sign' | 'signatures'>

// The signature binds the team and the input key, so a reference is valid only where the server wrote it.
// JSON encoding keeps the base unambiguous when an input key holds ':'.
const integrationRefSigningBase = (teamId: number, inputKey: string, id: IntegrationType['id']): string =>
    JSON.stringify([teamId, inputKey, String(id)])

export const signIntegrationRef = (
    signer: IntegrationRefSigner,
    teamId: number,
    inputKey: string,
    id: IntegrationType['id']
): string => signer.sign(INTEGRATION_REF_PURPOSE, integrationRefSigningBase(teamId, inputKey, id))

export const isSignedIntegrationRef = (
    signer: IntegrationRefSigner,
    teamId: number,
    inputKey: string,
    ref: IntegrationInputRef
): boolean => {
    const signature = ref[INTEGRATION_REF_SIG_KEY]
    if (typeof signature !== 'string') {
        return false
    }
    const given = Buffer.from(signature)
    return signer
        .signatures(INTEGRATION_REF_PURPOSE, integrationRefSigningBase(teamId, inputKey, ref[INTEGRATION_REF_KEY]))
        .some((accepted) => {
            const expected = Buffer.from(accepted)
            return expected.length === given.length && timingSafeEqual(expected, given)
        })
}

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null && !Array.isArray(value)

const isIntegrationId = (value: unknown): value is IntegrationType['id'] =>
    typeof value === 'number' || (typeof value === 'string' && value.length > 0)

export const isIntegrationRef = (value: unknown): value is IntegrationInputRef =>
    isPlainObject(value) && isIntegrationId(value[INTEGRATION_REF_KEY])

// Event data can hold an object shaped like a resolved integration, so only the objects that HogInputsService
// itself resolved become signed references. Anything else stays as it is.
const serverResolvedIntegrations = new WeakSet<object>()

export const markServerResolvedIntegration = <T extends object>(value: T): T => {
    serverResolvedIntegrations.add(value)
    return value
}

export const hasIntegrationRef = (inputs: Record<string, unknown>): boolean =>
    Object.values(inputs).some(
        (value) => isIntegrationRef(value) || (Array.isArray(value) && value.some(isIntegrationRef))
    )

/**
 * Replaces each integration input that the server resolved (and each such item of an integration_multi input) with a
 * signed reference.
 * Returns the same object when no input holds a resolved integration.
 */
export function replaceIntegrationInputsWithRefs(
    inputs: Record<string, any>,
    signRef: (inputKey: string, id: IntegrationType['id']) => string
): Record<string, any> {
    let changed = false
    const result: Record<string, any> = {}
    for (const [key, value] of Object.entries(inputs)) {
        const toRef = (item: unknown): unknown =>
            isPlainObject(item) && serverResolvedIntegrations.has(item) && isIntegrationId(item.$integration_id)
                ? {
                      [INTEGRATION_REF_KEY]: item.$integration_id,
                      [INTEGRATION_REF_SIG_KEY]: signRef(key, item.$integration_id),
                  }
                : item
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
