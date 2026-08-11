import { useValues } from 'kea'

import { SimpleKeyValueList } from 'lib/components/SimpleKeyValueList'

import { flagPayloadLogic } from './flagPayloadLogic'

export interface EventFlagsTabProps {
    properties: Record<string, any>
    promotedKeys?: string[]
}

export interface ReconstructionTarget {
    flagId: number
    version: number
    payloadKey: string
}

/**
 * Works out whether a flag's payload can be recovered from its version history, and under which
 * key in the flag's `payloads` map. Returns null when the event lacks the lookup keys or already
 * carries the payload itself.
 */
export function reconstructionTarget(properties: Record<string, any>): ReconstructionTarget | null {
    if ('$feature_flag_payload' in properties) {
        return null
    }

    const flagId = properties['$feature_flag_id']
    const version = properties['$feature_flag_version']
    const response = properties['$feature_flag_response']

    if (typeof flagId !== 'number' || typeof version !== 'number') {
        return null
    }

    // Boolean and remote config flags store their payload under "true"; multivariate flags
    // store one per variant.
    if (response === true) {
        return { flagId, version, payloadKey: 'true' }
    }
    if (typeof response === 'string' && response !== '') {
        return { flagId, version, payloadKey: response }
    }
    return null
}

/**
 * Mobile and server SDKs send the flag id and version on `$feature_flag_called` but not the
 * payload, so a remote config flag shows as enabled with no indication of what it served. The
 * payload is reconstructed from the flag's version history instead of being sent on the event.
 */
export function EventFlagsTab({ properties, promotedKeys }: EventFlagsTabProps): JSX.Element {
    const target = reconstructionTarget(properties)

    if (!target) {
        return <SimpleKeyValueList item={properties} promotedKeys={promotedKeys} />
    }

    return <ReconstructedFlagPayload properties={properties} promotedKeys={promotedKeys} target={target} />
}

function ReconstructedFlagPayload({
    properties,
    promotedKeys,
    target,
}: EventFlagsTabProps & { target: ReconstructionTarget }): JSX.Element {
    const { flagPayload } = useValues(flagPayloadLogic(target))

    return (
        <SimpleKeyValueList
            item={{ ...(flagPayload !== null ? { $feature_flag_payload: flagPayload } : {}), ...properties }}
            promotedKeys={promotedKeys}
        />
    )
}
