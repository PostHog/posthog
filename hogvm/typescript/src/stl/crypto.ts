import * as crypto from 'crypto'

export function sha256Hex(data: string): string {
    return crypto.createHash('sha256').update(data).digest('hex')
}

export function md5Hex(data: string): string {
    return crypto.createHash('md5').update(data).digest('hex')
}

export function sha256HmacChainHex(data: string[]): string {
    if (data.length < 2) {
        throw new Error('Data array must contain at least two elements.')
    }
    let hmac = crypto.createHmac('sha256', data[0])
    hmac.update(data[1])
    for (let i = 2; i < data.length; i++) {
        hmac = crypto.createHmac('sha256', hmac.digest())
        hmac.update(data[i])
    }
    return hmac.digest('hex')
}
