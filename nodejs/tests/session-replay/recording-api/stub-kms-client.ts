import {
    DecryptCommand,
    DecryptCommandOutput,
    GenerateDataKeyCommand,
    GenerateDataKeyCommandOutput,
    KMSClient,
    NotFoundException,
} from '@aws-sdk/client-kms'
import sodium from 'libsodium-wrappers'

/** The alias DynamoDBKeyStore asks for. Anything else is a bug the stub has to fail on, as KMS would. */
const MASTER_KEY_ALIAS = 'alias/session-replay-master-key'

/**
 * KMS compares the encryption context as a map, so the serialization has to be injective.
 * Joining `k=v` pairs is not: `{a: 'b&c=d'}` and `{a: 'b', c: 'd'}` produce the same string.
 * Real KMS also rejects non-string values, so the stub checks at runtime rather than trusting
 * the compile-time type, which a cast can bypass.
 */
const toAdditionalData = (context: Record<string, string> | undefined): Uint8Array => {
    const entries = Object.entries(context ?? {})
    for (const [key, value] of entries) {
        if (typeof value !== 'string') {
            throw new Error(`EncryptionContext values must be strings, got ${typeof value} for '${key}'`)
        }
    }
    return new TextEncoder().encode(JSON.stringify(entries.sort(([left], [right]) => left.localeCompare(right))))
}

/**
 * In-process stand-in for KMS, covering the two commands DynamoDBKeyStore issues.
 *
 * Data keys are wrapped under a per-instance master key with the EncryptionContext as additional
 * authenticated data, so a Decrypt whose context does not match the GenerateDataKey that produced
 * the blob throws, the same way real KMS rejects it. Both commands also reject an unrecognized
 * KeyId, which is what catches a keystore that asks for an alias nobody provisioned, and
 * GenerateDataKey requires NumberOfBytes in KMS's 1 to 1024 range.
 *
 * The keystore only ever asks KMS to wrap and unwrap bytes, so running that against a local
 * emulator instead proves nothing extra about AWS while costing a container.
 */
export async function createStubKmsClient(): Promise<KMSClient> {
    await sodium.ready
    const masterKey = sodium.crypto_aead_xchacha20poly1305_ietf_keygen()
    const nonceBytes = sodium.crypto_aead_xchacha20poly1305_ietf_NPUBBYTES

    const respond = (
        command: GenerateDataKeyCommand | DecryptCommand
    ): GenerateDataKeyCommandOutput | DecryptCommandOutput => {
        const { KeyId } = command.input
        if (KeyId !== MASTER_KEY_ALIAS) {
            throw new NotFoundException({ $metadata: {}, message: `Alias ${KeyId} is not defined` })
        }

        if (command instanceof GenerateDataKeyCommand) {
            const { NumberOfBytes, EncryptionContext } = command.input
            if (NumberOfBytes === undefined || NumberOfBytes < 1 || NumberOfBytes > 1024) {
                throw new Error(`GenerateDataKey requires NumberOfBytes between 1 and 1024, got ${NumberOfBytes}`)
            }
            const plaintext = sodium.randombytes_buf(NumberOfBytes)
            const nonce = sodium.randombytes_buf(nonceBytes)
            const wrapped = sodium.crypto_aead_xchacha20poly1305_ietf_encrypt(
                plaintext,
                toAdditionalData(EncryptionContext),
                null,
                nonce,
                masterKey
            )
            return { $metadata: {}, Plaintext: plaintext, CiphertextBlob: Buffer.concat([nonce, wrapped]) }
        }

        if (command instanceof DecryptCommand) {
            const { CiphertextBlob, EncryptionContext } = command.input
            if (!CiphertextBlob) {
                throw new Error('DecryptCommand requires a CiphertextBlob')
            }
            const blob = Buffer.from(CiphertextBlob)
            return {
                $metadata: {},
                Plaintext: sodium.crypto_aead_xchacha20poly1305_ietf_decrypt(
                    null,
                    blob.subarray(nonceBytes),
                    toAdditionalData(EncryptionContext),
                    blob.subarray(0, nonceBytes),
                    masterKey
                ),
            }
        }

        throw new Error('Stub KMS client received an unsupported command')
    }

    // The real send() is generically overloaded per command; the stub implements only the two the
    // keystore uses, so it is cast at this boundary rather than satisfying the full client type.
    return {
        send: (command: GenerateDataKeyCommand | DecryptCommand) => {
            try {
                return Promise.resolve(respond(command))
            } catch (error) {
                return Promise.reject(error)
            }
        },
        destroy: () => {},
    } as unknown as KMSClient
}
