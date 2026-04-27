import { hostname } from 'os'

// Mapped from the second octet of an `ip-A-B-C-D[.suffix]` Kubernetes node name.
// Mirrored in charts/library/templates/_kafka.tpl, charts/millpond/templates/statefulset.yaml,
// and the bash preambles in shared/{cdp,ingestion,logs}/common.yaml — all copies must move
// together until the chart-side derivation is removed.
export const OCTET_TO_AZ: Readonly<Record<string, string>> = Object.freeze({
    '20': 'use1-az6', // dev
    '21': 'use1-az1',
    '22': 'use1-az2',
    '30': 'use1-az2', // prod-us
    '31': 'use1-az4',
    '32': 'use1-az6',
    '40': 'euc1-az2', // prod-eu
    '41': 'euc1-az3',
    '42': 'euc1-az1',
})

export function deriveKafkaClientRack(nodeName: string | undefined): string | undefined {
    if (!nodeName) {
        console.warn(
            '[pod-identity] KAFKA_CLIENT_RACK could not be derived: K8S_NODE_NAME is not set. Cross-AZ Kafka traffic will not be optimised.'
        )
        return undefined
    }

    // Expected formats: `ip-10-22-99-1`, `ip-10-22-99-1.ec2.internal`. We want the second octet (e.g. `22`).
    const parts = nodeName.split('-')
    const octet = parts[2]
    if (!octet) {
        console.warn(
            `[pod-identity] KAFKA_CLIENT_RACK could not be derived: K8S_NODE_NAME=${nodeName} did not match the expected ip-A-B-C-D shape.`
        )
        return undefined
    }

    const az = OCTET_TO_AZ[octet]
    if (!az) {
        console.warn(
            `[pod-identity] KAFKA_CLIENT_RACK could not be derived: unknown second octet "${octet}" in K8S_NODE_NAME=${nodeName}. Update OCTET_TO_AZ in nodejs/src/common/pod-identity.ts.`
        )
        return undefined
    }

    return az
}

export function getPodName(): string {
    return process.env.POD_NAME || process.env.HOSTNAME || hostname()
}

/**
 * Assemble a Kafka client ID for the given target by reading per-target env
 * vars set by the chart, then substituting in the rack and pod name.
 *
 * Env vars read (all optional):
 * - `KAFKA_<TARGET>_CLIENT_ID_PREFIX` — emits `<prefix>_az=<rack>` when both
 *   the prefix env and the rack are present.
 * - `KAFKA_<TARGET>_CLIENT_ID_EXTRA` — comma-separated literal segment(s)
 *   inserted between rack and pod name (e.g. `ws_proxy_target=proxy-produce`).
 *
 * The pod name is always appended as the last segment. Empty segments are
 * skipped so `_az=,podname` cannot appear when the rack is missing.
 *
 * Callers are expected to gate this on `KAFKA_AUTO_DERIVE_CLIENT_ID` and to
 * still let an explicit `KAFKA_<TARGET>_CLIENT_ID` env var win — see
 * `consumer.ts` and `producer.ts` for the wiring pattern.
 */
export function assembleKafkaClientId(
    target: string,
    { rack, podName }: { rack: string | undefined; podName: string }
): string {
    const prefix = process.env[`KAFKA_${target}_CLIENT_ID_PREFIX`]
    const extra = process.env[`KAFKA_${target}_CLIENT_ID_EXTRA`]
    const segments: string[] = []

    if (prefix && rack) {
        segments.push(`${prefix}_az=${rack}`)
    }
    if (extra) {
        segments.push(extra)
    }
    segments.push(podName)

    return segments.join(',')
}

export function isAutoDeriveClientIdEnabled(): boolean {
    return process.env.KAFKA_AUTO_DERIVE_CLIENT_ID === 'true'
}
