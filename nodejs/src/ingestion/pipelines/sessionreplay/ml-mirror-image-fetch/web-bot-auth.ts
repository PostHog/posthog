import { KeyObject, createHash, createPrivateKey, createPublicKey, randomBytes, sign } from 'node:crypto'

const SIGNATURE_AGENT_URL = 'https://us.posthog.com/.well-known/http-message-signatures-directory'
const SIGNATURE_AGENT_HEADER = JSON.stringify(SIGNATURE_AGENT_URL)
const SIGNATURE_LIFETIME_SECONDS = 60

type SigningKey = {
    privateKey: KeyObject
    keyId: string
}

export interface WebBotAuthRequestSigner {
    headersFor(url: string): Record<string, string>
}

export function createWebBotAuthRequestSigner(commaSeparatedPrivateKeyPems: string): WebBotAuthRequestSigner {
    const privateKeyPems = commaSeparatedPrivateKeyPems.split(',')
    if (privateKeyPems.length === 1 && privateKeyPems[0].trim() === '') {
        throw new Error('WEB_BOT_AUTH_PRIVATE_KEYS must contain at least one Ed25519 private key')
    }

    const signingKeys = privateKeyPems.map((privateKeyPem, index) => loadSigningKey(privateKeyPem, index + 1))
    return new Ed25519WebBotAuthRequestSigner(signingKeys)
}

class Ed25519WebBotAuthRequestSigner implements WebBotAuthRequestSigner {
    constructor(private readonly signingKeys: SigningKey[]) {}

    public headersFor(url: string): Record<string, string> {
        const authority = new URL(url).host
        const created = Math.floor(Date.now() / 1000)
        const expires = created + SIGNATURE_LIFETIME_SECONDS
        const signatureInputs: string[] = []
        const signatures: string[] = []

        for (const [index, signingKey] of this.signingKeys.entries()) {
            const label = `sig${index + 1}`
            const nonce = randomBytes(64).toString('base64url')
            const parameters =
                `("@authority" "signature-agent");created=${created};keyid="${signingKey.keyId}";` +
                `alg="ed25519";expires=${expires};nonce="${nonce}";tag="web-bot-auth"`
            const signatureBase =
                `"@authority": ${authority}\n` +
                `"signature-agent": ${SIGNATURE_AGENT_HEADER}\n` +
                `"@signature-params": ${parameters}`

            signatureInputs.push(`${label}=${parameters}`)
            signatures.push(
                `${label}=:${sign(null, Buffer.from(signatureBase), signingKey.privateKey).toString('base64')}:`
            )
        }

        return {
            // Cloudflare rejects the dictionary form from newer drafts, so use the compatible structured string.
            'signature-agent': SIGNATURE_AGENT_HEADER,
            'signature-input': signatureInputs.join(', '),
            signature: signatures.join(', '),
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
