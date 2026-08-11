import {
    DecryptCommand,
    DecryptCommandOutput,
    GenerateDataKeyCommand,
    GenerateDataKeyCommandOutput,
    KMSClient,
} from '@aws-sdk/client-kms'
import sodium from 'libsodium-wrappers'

/** KMS canonicalizes the encryption context, so a stable serialization is what binds the two calls. */
const toAdditionalData = (context: Record<string, string> | undefined): Uint8Array =>
    new TextEncoder().encode(
        Object.entries(context ?? {})
            .sort(([left], [right]) => left.localeCompare(right))
            .map(([key, value]) => `${key}=${value}`)
            .join('&')
    )

/**
 * In-process stand-in for KMS, covering the two commands DynamoDBKeyStore issues.
 *
 * Data keys are wrapped under a per-instance master key with the EncryptionContext as additional
 * authenticated data, so a Decrypt whose context does not match the GenerateDataKey that produced
 * the blob throws, the same way real KMS rejects it. The keystore only ever asks KMS to wrap and
 * unwrap bytes, so running that against a local emulator instead proves nothing extra about AWS
 * while costing a container.
 */
export async function createStubKmsClient(): Promise<KMSClient> {
    await sodium.ready
    const masterKey = sodium.crypto_aead_xchacha20poly1305_ietf_keygen()
    const nonceBytes = sodium.crypto_aead_xchacha20poly1305_ietf_NPUBBYTES

    const send = (command: GenerateDataKeyCommand | DecryptCommand): Promise<unknown> => {
        if (command instanceof GenerateDataKeyCommand) {
            const { NumberOfBytes, EncryptionContext } = command.input
            const plaintext = sodium.randombytes_buf(NumberOfBytes ?? sodium.crypto_secretbox_KEYBYTES)
            const nonce = sodium.randombytes_buf(nonceBytes)
            const wrapped = sodium.crypto_aead_xchacha20poly1305_ietf_encrypt(
                plaintext,
                toAdditionalData(EncryptionContext),
                null,
                nonce,
                masterKey
            )
            const output: GenerateDataKeyCommandOutput = {
                $metadata: {},
                Plaintext: plaintext,
                CiphertextBlob: Buffer.concat([Buffer.from(nonce), Buffer.from(wrapped)]),
            }
            return Promise.resolve(output)
        }

        if (command instanceof DecryptCommand) {
            const { CiphertextBlob, EncryptionContext } = command.input
            if (!CiphertextBlob) {
                return Promise.reject(new Error('DecryptCommand requires a CiphertextBlob'))
            }
            const blob = Buffer.from(CiphertextBlob)
            const output: DecryptCommandOutput = {
                $metadata: {},
                Plaintext: sodium.crypto_aead_xchacha20poly1305_ietf_decrypt(
                    null,
                    blob.subarray(nonceBytes),
                    toAdditionalData(EncryptionContext),
                    blob.subarray(0, nonceBytes),
                    masterKey
                ),
            }
            return Promise.resolve(output)
        }

        return Promise.reject(new Error('Stub KMS client received an unsupported command'))
    }

    // The real send() is generically overloaded per command; the stub implements only the two the
    // keystore uses, so it is cast at this boundary rather than satisfying the full client type.
    return { send, destroy: () => {} } as unknown as KMSClient
}
