import { createHash } from 'crypto'

export const encodePrivateField = (property: string, salt: string) =>
    createHash('sha256')
        .update(property + salt)
        .digest('hex')
