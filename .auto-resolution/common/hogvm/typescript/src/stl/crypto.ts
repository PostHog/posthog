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

export function sha256HmacChain(
    data: string[],
    encoding: 'hex' | 'base64' | 'base64url' | 'binary' = 'hex',
    options?: ExecOptions
): string {
    const crypto = options?.external?.crypto
    if (!crypto) {
        throw new Error('The crypto module is required for "sha256HmacChainHex" to work.')
    }
    if (data.length < 2) {
        throw new Error('Data array must contain at least two elements.')
    }
    let hmac = crypto.createHmac('sha256', data[0])
    hmac.update(data[1])
    for (let i = 2; i < data.length; i++) {
        hmac = crypto.createHmac('sha256', hmac.digest())
        hmac.update(data[i])
    }
    return hmac.digest(encoding)
}
