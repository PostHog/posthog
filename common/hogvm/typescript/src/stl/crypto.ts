import { ExecOptions } from '../types'

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
        throw new Error('The crypto module is required for "sha256Hex" to work.')
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
        throw new Error('The crypto module is required for "md5Hex" to work.')
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
        throw new Error('The crypto module is required for "sha1Hex" to work.')
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
        throw new Error(`The crypto module is required for "${name}" to work.`)
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
