import * as crypto from 'crypto'

export function sha256Hex(data: string): string {
    return crypto.createHash('sha256').update(data).digest('hex')
}

export function md5Hex(data: string): string {
    return crypto.createHash('md5').update(data).digest('hex')
}
