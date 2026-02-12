import { isCloud } from '../../utils/env-utils'
import { KeyStore, RecordingDecryptor, RecordingEncryptor } from '../types'
import { CleartextRecordingDecryptor } from './cleartext-decryptor'
import { CleartextRecordingEncryptor } from './cleartext-encryptor'
import { SodiumRecordingDecryptor } from './sodium-decryptor'
import { SodiumRecordingEncryptor } from './sodium-encryptor'

// Re-export all crypto implementations for convenience
export { CleartextRecordingDecryptor } from './cleartext-decryptor'
export { CleartextRecordingEncryptor } from './cleartext-encryptor'
export { SodiumRecordingDecryptor } from './sodium-decryptor'
export { SodiumRecordingEncryptor } from './sodium-encryptor'

export function getBlockEncryptor(keyStore: KeyStore): RecordingEncryptor {
    if (isCloud()) {
        return new SodiumRecordingEncryptor(keyStore)
    }
    return new CleartextRecordingEncryptor(keyStore)
}

export function getBlockDecryptor(keyStore: KeyStore): RecordingDecryptor {
    if (isCloud()) {
        return new SodiumRecordingDecryptor(keyStore)
    }
    return new CleartextRecordingDecryptor(keyStore)
}
