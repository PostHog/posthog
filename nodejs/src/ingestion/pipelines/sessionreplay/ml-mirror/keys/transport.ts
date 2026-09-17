import { Message } from 'node-rdkafka'

import { parseKafkaHeaders } from '~/common/kafka/consumer/consumer-v1'
import { parseJSON } from '~/common/utils/json-parse'
import { parseImageRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'
import { MlMirrorMetrics } from '~/ingestion/pipelines/sessionreplay/ml-mirror/metrics'
import { sessionStartMonth } from '~/ingestion/pipelines/sessionreplay/ml-mirror/session-identifier-format'

import { MlDataKey } from './crypto'
import { MlKeyReader } from './reader'
import { INGESTION_VERSION_HEADER, MlWireVersion, sessionKeyId, tableKeyString } from './schema'

export interface MlDecodedMessage {
    message: Message
    original: Message
    version?: 1 | 2
    key?: MlDataKey
    invalid?: true
    /** A record in the sealed envelope shape the lanes wrote before cleartext records; consumers skip it. */
    legacy?: true
}

export interface MlSessionIdentityLocator {
    (message: Message): { teamId: number; sessionId: string } | null
}

export function ingestionVersion(message: Pick<Message, 'headers'>): 1 | 2 {
    const version = parseKafkaHeaders(message.headers)[INGESTION_VERSION_HEADER]
    if (version === undefined || version === '1') {
        return 1
    }
    if (version === '2') {
        return 2
    }
    throw new Error('Unsupported ML ingestion version')
}

/** Only a v2 session has a key, so the key decides the version every producer stamps. */
export function mlWireVersion(key: MlDataKey | undefined): MlWireVersion {
    return key ? '2' : '1'
}

/** Kafka carries the record in cleartext; the header tells consumers which identifier scheme and datasets it belongs to. */
export function mlKafkaRecord(
    version: MlWireVersion,
    value: Buffer
): { value: Buffer; headers: Record<string, string> } {
    return { value, headers: { [INGESTION_VERSION_HEADER]: version } }
}

export function validateImageOwner(ref: string, key: MlDataKey | undefined): void {
    const parsed = parseImageRef(ref)
    if (key) {
        if (
            !parsed ||
            parsed.version !== 2 ||
            parsed.teamId !== String(key.identity.teamId) ||
            parsed.sessionMonth !== sessionStartMonth(key.identity.sessionId ?? '')
        ) {
            throw new Error('ML image reference ownership mismatch')
        }
    } else if (parsed?.version === 2) {
        throw new Error('An ML v2 image requires a v2 session key')
    }
}

export function validateImageRefVersion(ref: string, version: 1 | 2): void {
    const parsed = parseImageRef(ref)
    if (version === 2 ? parsed?.version !== 2 : parsed?.version === 2) {
        throw new Error('ML image reference version mismatch')
    }
}

function isLegacyEnvelope(value: Buffer | null | undefined): boolean {
    if (!value?.length || value[0] !== 0x7b) {
        return false
    }
    try {
        const parsed: unknown = parseJSON(value.toString())
        return (
            !!parsed &&
            typeof parsed === 'object' &&
            (parsed as { v?: unknown }).v === 2 &&
            typeof (parsed as { nonce?: unknown }).nonce === 'string' &&
            typeof (parsed as { ciphertext?: unknown }).ciphertext === 'string'
        )
    } catch {
        return false
    }
}

export class MlKafkaTransport {
    constructor(private readonly reader: MlKeyReader) {}

    /**
     * Classifies a batch by wire version and, when the caller names the session each record belongs to, resolves
     * that session's key so the caller can seal its output. A record whose session key is deleted or blocked is
     * dropped, so the caller can count the gap. A blocked team is refused on every read, while a deleted session is
     * still served while a process holds its cached row, for the row cache lifetime.
     */
    public async read(
        messages: Message[],
        options: { bindKafkaKey?: boolean; sessionIdentity?: MlSessionIdentityLocator } = {}
    ): Promise<MlDecodedMessage[]> {
        const versions = new Map<Message, 1 | 2>()
        const identities = new Map<Message, { teamId: number; sessionId: string }>()
        const invalid = new Set<Message>()
        const legacy = new Set<Message>()
        for (const message of messages) {
            try {
                const version = ingestionVersion(message)
                versions.set(message, version)
                if (version === 2 && isLegacyEnvelope(message.value)) {
                    legacy.add(message)
                    continue
                }
                if (options.bindKafkaKey) {
                    validateImageRefVersion(message.key?.toString() ?? '', version)
                }
                if (version === 2 && options.sessionIdentity) {
                    const identity = options.sessionIdentity(message)
                    if (!identity || !Number.isSafeInteger(identity.teamId) || identity.teamId <= 0) {
                        throw new Error('Missing ML session identity')
                    }
                    sessionStartMonth(identity.sessionId)
                    identities.set(message, identity)
                }
            } catch {
                invalid.add(message)
            }
        }
        const keys = identities.size
            ? await this.reader.read(
                  [...identities.values()].map((identity) => sessionKeyId(identity.teamId, identity.sessionId))
              )
            : new Map<string, MlDataKey>()
        MlMirrorMetrics.incrementMlLegacyEnvelopesDropped(legacy.size)
        const result: MlDecodedMessage[] = []
        for (const original of messages) {
            if (legacy.has(original)) {
                result.push({ original, message: original, version: 2, legacy: true })
                continue
            }
            if (invalid.has(original)) {
                result.push({ original, message: original, version: versions.get(original), invalid: true })
                continue
            }
            const version = versions.get(original)!
            const identity = identities.get(original)
            if (!identity) {
                result.push({ original, message: original, version })
                continue
            }
            const key = keys.get(tableKeyString(sessionKeyId(identity.teamId, identity.sessionId)))
            if (key) {
                result.push({ original, message: original, version, key })
            }
        }
        return result
    }
}
