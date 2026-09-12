import { Message } from 'node-rdkafka'

import { parseKafkaHeaders } from '~/common/kafka/consumer/consumer-v1'
import { parseJSON } from '~/common/utils/json-parse'
import { parseImageRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'
import { sessionStartMonth } from '~/ingestion/pipelines/sessionreplay/ml-mirror/session-identifier-format'

import { MlDataKey, MlEncryptedEnvelope, MlKeyReadExpiredError, decryptEnvelope, encryptEnvelope } from './crypto'
import { MlKeyReader } from './reader'
import { CONSENT_GRANTED_AT_HEADER, INGESTION_VERSION_HEADER, sessionKeyId, tableKeyString } from './schema'

export interface MlDecodedMessage {
    message: Message
    original: Message
    key?: MlDataKey
    invalid?: true
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

export function encryptedKafkaValue(
    key: MlDataKey | undefined,
    kind: string,
    value: Buffer,
    ref?: string
): { value: Buffer; headers: Record<string, string> } {
    return key
        ? {
              value: encryptEnvelope(key, kind, value, ref),
              headers: {
                  [INGESTION_VERSION_HEADER]: '2',
                  [CONSENT_GRANTED_AT_HEADER]: String(key.identity.consentGrantedAt),
              },
          }
        : { value, headers: { [INGESTION_VERSION_HEADER]: '1' } }
}

export function validateImageOwner(ref: string, key: MlDataKey | undefined): void {
    const parsed = parseImageRef(ref)
    if (key) {
        if (
            !parsed ||
            parsed.version !== 2 ||
            parsed.teamId !== String(key.identity.teamId) ||
            parsed.consentGrantedAt !== key.identity.consentGrantedAt ||
            parsed.sessionMonth !== sessionStartMonth(key.identity.sessionId ?? '')
        ) {
            throw new Error('ML image reference ownership mismatch')
        }
    } else if (parsed?.version === 2) {
        throw new Error('An ML v2 image requires an encrypted message')
    }
}

export class MlKafkaEncryption {
    constructor(private readonly reader: MlKeyReader) {}

    public async read(messages: Message[], kind: string, bindKafkaKey = false): Promise<MlDecodedMessage[]> {
        const envelopes = new Map<Message, MlEncryptedEnvelope>()
        const invalid = new Set<Message>()
        for (const message of messages) {
            try {
                if (ingestionVersion(message) === 1) {
                    continue
                }
                if (!message.value) {
                    throw new Error('Missing ML encrypted payload')
                }
                const envelope = parseJSON(message.value.toString()) as MlEncryptedEnvelope
                const context = envelope?.context
                if (
                    envelope.v !== 2 ||
                    !context ||
                    !Number.isSafeInteger(context.teamId) ||
                    context.teamId <= 0 ||
                    typeof context.organizationId !== 'string' ||
                    typeof context.sessionId !== 'string' ||
                    !Number.isSafeInteger(context.consentGrantedAt) ||
                    context.kind !== kind ||
                    parseKafkaHeaders(message.headers)[CONSENT_GRANTED_AT_HEADER] !== String(context.consentGrantedAt)
                ) {
                    throw new Error('Invalid ML encrypted payload context')
                }
                envelopes.set(message, envelope)
            } catch {
                invalid.add(message)
            }
        }
        const keys = await this.reader.read(
            [...envelopes.values()].map(({ context }) => sessionKeyId(context.teamId, context.sessionId!))
        )
        const result: MlDecodedMessage[] = []
        for (const original of messages) {
            if (invalid.has(original)) {
                result.push({ original, message: original, invalid: true })
                continue
            }
            try {
                const envelope = envelopes.get(original)
                if (!envelope) {
                    if (bindKafkaKey) {
                        validateImageOwner(original.key?.toString() ?? '', undefined)
                    }
                    result.push({ message: original, original })
                    continue
                }
                const key = keys.get(tableKeyString(sessionKeyId(envelope.context.teamId, envelope.context.sessionId!)))
                if (!key) {
                    continue
                }
                const ref = bindKafkaKey ? original.key?.toString() : undefined
                if (bindKafkaKey) {
                    validateImageOwner(ref ?? '', key)
                }
                const value = decryptEnvelope(key, envelope, kind, ref)
                result.push({ original, message: { ...original, value, size: value.length }, key })
            } catch (error) {
                if (error instanceof MlKeyReadExpiredError) {
                    throw error
                }
                result.push({ original, message: original, invalid: true })
            }
        }
        return result
    }
}
