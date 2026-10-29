import { ExecOptions } from '../types'
import { HogVMException } from '../utils'

export function sha256(
    data: string | null,
    encoding: 'hex' | 'base64' | 'base64url' | 'binary' = 'hex',
    options?: ExecOptions
): string | null {
    if (data === null) {
        return null
    }
    const crypto = options?.external?.crypto
    if (!crypto) {
        throw new HogVMException('The crypto module is required for "sha256Hex" to work.', 'contract')
    }
    return crypto.createHash('sha256').update(data).digest(encoding)
}

export function md5(
    data: string | null,
    encoding: 'hex' | 'base64' | 'base64url' | 'binary' = 'hex',
    options?: ExecOptions
): string | null {
    if (data === null) {
        return null
    }
    const crypto = options?.external?.crypto
    if (!crypto) {
        throw new HogVMException('The crypto module is required for "md5Hex" to work.', 'contract')
    }
    return crypto.createHash('md5').update(data).digest(encoding)
}

// SHA-1 is only here because vendors sign webhooks with it. Never pick it for new work.
export function sha1(
    data: string | null,
    encoding: 'hex' | 'base64' | 'base64url' | 'binary' = 'hex',
    options?: ExecOptions
): string | null {
    if (data === null) {
        return null
    }
    const crypto = options?.external?.crypto
    if (!crypto) {
        throw new HogVMException('The crypto module is required for "sha1Hex" to work.', 'contract')
    }
    return crypto.createHash('sha1').update(data).digest(encoding)
}

function hmacChain(
    algorithm: 'sha256' | 'sha1',
    name: string,
    data: string[],
    encoding: 'hex' | 'base64' | 'base64url' | 'binary',
    options?: ExecOptions
): string {
    const crypto = options?.external?.crypto
    if (!crypto) {
        throw new HogVMException(`The crypto module is required for "${name}" to work.`, 'contract')
    }
    if (data.length < 2) {
        throw new Error('Data array must contain at least two elements.')
    }
    let hmac = crypto.createHmac(algorithm, data[0])
    hmac.update(data[1])
    for (let i = 2; i < data.length; i++) {
        hmac = crypto.createHmac(algorithm, hmac.digest())
        hmac.update(data[i])
    }
    return hmac.digest(encoding)
}

export function sha256HmacChain(
    data: string[],
    encoding: 'hex' | 'base64' | 'base64url' | 'binary' = 'hex',
    options?: ExecOptions
): string {
    return hmacChain('sha256', 'sha256HmacChainHex', data, encoding, options)
}

export function sha1HmacChain(
    data: string[],
    encoding: 'hex' | 'base64' | 'base64url' | 'binary' = 'hex',
    options?: ExecOptions
): string {
    return hmacChain('sha1', 'sha1HmacChainHex', data, encoding, options)
}

// HMAC-SHA256 with a base64 encoded binary key. Svix-style webhook secrets are random bytes, which a
// string key would corrupt.
export function sha256HmacBase64Key(
    key: string,
    data: string,
    encoding: 'hex' | 'base64' | 'base64url' | 'binary' = 'hex',
    options?: ExecOptions
): string {
    const crypto = options?.external?.crypto
    if (!crypto) {
        throw new HogVMException('The crypto module is required for "sha256HmacBase64Key" to work.', 'contract')
    }
    return crypto.createHmac('sha256', Buffer.from(key, 'base64')).update(data).digest(encoding)
}

// DER prefix of an Ed25519 SubjectPublicKeyInfo. Node only imports public keys in a container format.
const ED25519_SPKI_PREFIX = Buffer.from('302a300506032b6570032100', 'hex')

function decodeVerifyArg(value: string, encoding: 'hex' | 'base64', expectedBytes: number): Buffer | null {
    if (encoding === 'hex' && !/^(?:[0-9a-fA-F]{2})*$/.test(value)) {
        return null
    }
    const bytes = Buffer.from(value, encoding)
    return bytes.length === expectedBytes ? bytes : null
}

// Returns false for a malformed key or signature, so a bad webhook reads as unverified, not as a crash.
export function ed25519Verify(
    message: string | null,
    signature: string | null,
    publicKey: string | null,
    encoding: 'hex' | 'base64' = 'hex',
    options?: ExecOptions
): boolean {
    const crypto = options?.external?.crypto
    if (!crypto) {
        throw new HogVMException('The crypto module is required for "ed25519Verify" to work.', 'contract')
    }
    if (encoding !== 'hex' && encoding !== 'base64') {
        throw new HogVMException(`ed25519Verify: encoding must be 'hex' or 'base64', got '${encoding}'`, 'data')
    }
    if (typeof message !== 'string' || typeof signature !== 'string' || typeof publicKey !== 'string') {
        return false
    }
    const signatureBytes = decodeVerifyArg(signature.trim(), encoding, 64)
    const keyBytes = decodeVerifyArg(publicKey.trim(), encoding, 32)
    if (!signatureBytes || !keyBytes) {
        return false
    }
    try {
        const key = crypto.createPublicKey({
            key: Buffer.concat([ED25519_SPKI_PREFIX, keyBytes]),
            format: 'der',
            type: 'spki',
        })
        return crypto.verify(null, Buffer.from(message), key, signatureBytes)
    } catch {
        return false
    }
}
