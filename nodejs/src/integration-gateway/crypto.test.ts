import crypto from 'crypto'
import { Fernet } from 'fernet-nodejs'

import { IntegrationDecryptor } from './crypto'

function legacyFernetKey(secret: string, salt: string): string {
    return crypto
        .pbkdf2Sync(secret, salt, 100_000, 32, 'sha256')
        .toString('base64')
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
}

// 32 bytes — matches the dev default of ENCRYPTION_SALT_KEYS.
const SALT_KEY_32 = '00beef0000beef0000beef0000beef00'

// Cross-implementation parity fixtures produced by Python's `cryptography` Fernet (the exact
// library + key derivation Django's EncryptedJSONField uses) under the dev ENCRYPTION_SALT_KEYS
// default. If key derivation drifts, these stop decrypting — which in prod means silently failing
// to read every Django-written credential. Regenerate with:
//   python3 -c "import base64; from cryptography.fernet import Fernet, MultiFernet; \
//     f=MultiFernet([Fernet(base64.urlsafe_b64encode(b'00beef0000beef0000beef0000beef00'))]); \
//     print(f.encrypt(b'django-produced-access-token').decode())"
const DJANGO_ACCESS_TOKEN_CIPHERTEXT =
    'gAAAAABqV056wiDg4SFg1WMXPi0eSlEqDSqNapKDGEOjxStwnQdRnt2XsLu-lfRiXBq3Y3WZUtpKmjDJp8xPkMVh-iZyUGbSf8Q24WUeLApdA4ilqpLjUSY='
const DJANGO_REFRESH_TOKEN_CIPHERTEXT =
    'gAAAAABqV056405em_3t-Gy4hfqS4x7PqxbufIr5T5sUaNHRBHVU5pl0rTcL-V06r0Bb1bO2FXLbCe8_EMoAKjGh1veSsDvsyXC7BsCGorv61P2cQDYV_m8='

describe('IntegrationDecryptor', () => {
    const saltKeyOnly = (): IntegrationDecryptor => new IntegrationDecryptor([SALT_KEY_32], [], [])

    it('decrypts Django-produced ciphertext (byte-for-byte parity with EncryptedJSONField)', () => {
        const d = saltKeyOnly()
        expect(d.decryptLeaf(DJANGO_ACCESS_TOKEN_CIPHERTEXT)).toEqual('django-produced-access-token')
        expect(d.decryptLeaf(DJANGO_REFRESH_TOKEN_CIPHERTEXT)).toEqual('django-produced-refresh-token')
    })

    it('decrypts a legacy PBKDF2-derived leaf (SECRET_KEY + SALT_KEY path)', () => {
        // A value written before the salt-keys rework must stay readable via the legacy keys.
        const secret = 'django-secret-key'
        const salt = 'some-salt'
        const token = new Fernet(legacyFernetKey(secret, salt)).encrypt('legacy-value')

        expect(new IntegrationDecryptor([SALT_KEY_32], [secret], [salt]).decryptLeaf(token)).toEqual('legacy-value')
        // Without the legacy key it's undecryptable — proving the legacy derivation is what reads it.
        expect(saltKeyOnly().decryptLeaf(token)).toBeUndefined()
    })

    it('encryptLeaf round-trips under the primary key so refreshed tokens stay Django-readable', () => {
        const d = saltKeyOnly()
        const token = d.encryptLeaf('rotated-access-token')
        // A decryptor built with ONLY the salt key recovers it => encrypted under the primary key.
        expect(new IntegrationDecryptor([SALT_KEY_32], [], []).decryptLeaf(token)).toEqual('rotated-access-token')
    })

    it('walks nested sensitive_config, decrypting string leaves and passing everything else through', () => {
        const d = saltKeyOnly()
        const encrypted = {
            access_token: DJANGO_ACCESS_TOKEN_CIPHERTEXT,
            nested: { refresh_token: DJANGO_REFRESH_TOKEN_CIPHERTEXT },
            not_encrypted: 'plain', // undecryptable -> passthrough (ignore_decrypt_errors)
            id_token: null,
            count: 3,
        }
        expect(d.decryptSensitiveConfig(encrypted)).toEqual({
            access_token: 'django-produced-access-token',
            nested: { refresh_token: 'django-produced-refresh-token' },
            not_encrypted: 'plain',
            id_token: null,
            count: 3,
        })
    })

    it('refuses to build with no usable primary key (never runs decrypt-only)', () => {
        expect(() => new IntegrationDecryptor([], ['secret'], ['salt'])).toThrow(/no usable primary decryption keys/)
    })
})
