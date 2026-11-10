import { KeyObject, createHash, createPrivateKey, createPublicKey, randomBytes, sign } from 'node:crypto'

const SIGNATURE_AGENT_URL = 'https://us.posthog.com/.well-known/http-message-signatures-directory'
const SIGNATURE_AGENT_HEADER = JSON.stringify(SIGNATURE_AGENT_URL)
const SIGNATURE_LIFETIME_SECONDS = 60
const REQUEST_METHOD = 'GET'

type SigningKey = {
    privateKey: KeyObject
    keyId: string
}

export interface WebBotAuthRequestSigner {
    headersForGet(url: string): Record<string, string>
}

export function createWebBotAuthRequestSigner(commaSeparatedPrivateKeyPems: string): WebBotAuthRequestSigner {
    const privateKeyPems = commaSeparatedPrivateKeyPems.split(',')
    if (privateKeyPems.length === 1 && privateKeyPems[0].trim() === '') {
        throw new Error('WEB_BOT_AUTH_PRIVATE_KEYS must contain at least one Ed25519 private key')
    }

    const signingKeys = privateKeyPems.map((privateKeyPem, index) => loadSigningKey(privateKeyPem, index + 1))
    return new Ed25519WebBotAuthRequestSigner(signingKeys[0])
}

class Ed25519WebBotAuthRequestSigner implements WebBotAuthRequestSigner {
    constructor(private readonly signingKey: SigningKey) {}

    public headersForGet(url: string): Record<string, string> {
        const targetUrl = new URL(url)
        targetUrl.hash = ''
        const authority = targetUrl.host
        const targetUri = targetUrl.toString()
        const created = Math.floor(Date.now() / 1000)
        const expires = created + SIGNATURE_LIFETIME_SECONDS
        const nonce = randomBytes(64).toString('base64url')
        const parameters =
            `("@method" "@authority" "@target-uri" "signature-agent");created=${created};keyid="${this.signingKey.keyId}";` +
            `alg="ed25519";expires=${expires};nonce="${nonce}";tag="web-bot-auth"`
        const signatureBase =
            `"@method": ${REQUEST_METHOD}\n` +
            `"@authority": ${authority}\n` +
            `"@target-uri": ${targetUri}\n` +
            `"signature-agent": ${SIGNATURE_AGENT_HEADER}\n` +
            `"@signature-params": ${parameters}`

        return {
            // Cloudflare rejects the dictionary form from newer drafts, so use the compatible structured string.
            'signature-agent': SIGNATURE_AGENT_HEADER,
            'signature-input': `sig1=${parameters}`,
            signature: `sig1=:${sign(null, Buffer.from(signatureBase), this.signingKey.privateKey).toString('base64')}:`,
        }
    }
}

function loadSigningKey(privateKeyPem: string, keyIndex: number): SigningKey {
    let privateKey: KeyObject
    try {
        privateKey = createPrivateKey(privateKeyPem.trim().replaceAll('\\n', '\n'))
    } catch {
        throw new Error(`WEB_BOT_AUTH_PRIVATE_KEYS entry ${keyIndex} could not be loaded`)
    }
    if (privateKey.asymmetricKeyType !== 'ed25519') {
        throw new Error(`WEB_BOT_AUTH_PRIVATE_KEYS entry ${keyIndex} is not an Ed25519 private key`)
    }

    const publicJwk = createPublicKey(privateKey).export({ format: 'jwk' })
    if (publicJwk.kty !== 'OKP' || publicJwk.crv !== 'Ed25519' || !publicJwk.x) {
        throw new Error(`WEB_BOT_AUTH_PRIVATE_KEYS entry ${keyIndex} has an invalid public key`)
    }
    const canonicalJwk = JSON.stringify({ crv: publicJwk.crv, kty: publicJwk.kty, x: publicJwk.x })
    const keyId = createHash('sha256').update(canonicalJwk).digest('base64url')
    return { privateKey, keyId }
}
