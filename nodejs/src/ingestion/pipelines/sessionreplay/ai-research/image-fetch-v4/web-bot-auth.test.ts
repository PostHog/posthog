import { KeyObject, createHash, generateKeyPairSync, verify as verifySignature } from 'node:crypto'

import { createWebBotAuthRequestSigner } from './web-bot-auth'

const SIGNATURE_AGENT = '"https://us.posthog.com/.well-known/http-message-signatures-directory"'

type TestKeyPair = {
    privateKeyPem: string
    publicKey: KeyObject
}

function generateEd25519KeyPair(): TestKeyPair {
    const { privateKey, publicKey } = generateKeyPairSync('ed25519')
    return {
        privateKeyPem: privateKey.export({ format: 'pem', type: 'pkcs8' }).toString(),
        publicKey,
    }
}

function keyId(publicKey: KeyObject): string {
    const jwk = publicKey.export({ format: 'jwk' })
    const canonicalJwk = JSON.stringify({ crv: jwk.crv, kty: jwk.kty, x: jwk.x })
    return createHash('sha256').update(canonicalJwk).digest('base64url')
}

function expectSignedHeadersToVerify(
    method: string,
    url: string,
    headers: Record<string, string>,
    publicKey: KeyObject,
    label: string,
    expectedResult = true
): void {
    const signatureInput = headers['signature-input'].split(', ').find((member) => member.startsWith(`${label}=`))
    const signature = headers.signature.split(', ').find((member) => member.startsWith(`${label}=`))
    if (!signatureInput || !signature) {
        throw new Error(`Missing ${label}`)
    }

    const parameters = signatureInput.slice(label.length + 1)
    const parametersMatch = parameters.match(
        /^\("@method" "@authority" "@target-uri" "signature-agent"\);created=(\d+);keyid="([^"]+)";alg="ed25519";expires=(\d+);nonce="([^"]+)";tag="web-bot-auth"$/
    )
    if (!parametersMatch) {
        throw new Error(`Invalid ${label} parameters`)
    }
    const [, created, actualKeyId, expires, nonce] = parametersMatch
    expect(actualKeyId).toBe(keyId(publicKey))
    expect(Number(expires) - Number(created)).toBe(60)
    expect(Buffer.from(nonce, 'base64url')).toHaveLength(64)

    const targetUrl = new URL(url)
    targetUrl.hash = ''
    const signatureBase =
        `"@method": ${method}\n` +
        `"@authority": ${targetUrl.host}\n` +
        `"@target-uri": ${targetUrl.toString()}\n` +
        `"signature-agent": ${SIGNATURE_AGENT}\n` +
        `"@signature-params": ${parameters}`
    const signatureBytes = Buffer.from(signature.slice(`${label}=:`.length, -1), 'base64')
    expect(verifySignature(null, Buffer.from(signatureBase), publicKey, signatureBytes)).toBe(expectedResult)
}

describe('Web Bot Auth request signing', () => {
    beforeEach(() => {
        jest.useFakeTimers().setSystemTime(new Date('2026-08-19T08:00:00Z'))
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('creates a Cloudflare-compatible signature with current protocol parameters', () => {
        const keyPair = generateEd25519KeyPair()
        const signer = createWebBotAuthRequestSigner(keyPair.privateKeyPem)
        const url = 'https://cdn.example.com/image.png?size=large'

        const headers = signer.headersForGet(url)

        expect(headers['signature-agent']).toBe(SIGNATURE_AGENT)
        expectSignedHeadersToVerify('GET', url, headers, keyPair.publicKey, 'sig1')
    })

    it.each([
        ['a different method', 'POST', 'https://cdn.example.com/image.png?size=large'],
        ['a different path', 'GET', 'https://cdn.example.com/other.png?size=large'],
        ['a different query', 'GET', 'https://cdn.example.com/image.png?size=small'],
    ])('does not verify for %s', (_name, method, replayUrl) => {
        const keyPair = generateEd25519KeyPair()
        const signer = createWebBotAuthRequestSigner(keyPair.privateKeyPem)
        const headers = signer.headersForGet('https://cdn.example.com/image.png?size=large')

        expectSignedHeadersToVerify(method, replayUrl, headers, keyPair.publicKey, 'sig1', false)
    })

    it('signs with the first configured key during rotation', () => {
        const firstKeyPair = generateEd25519KeyPair()
        const secondKeyPair = generateEd25519KeyPair()
        const signer = createWebBotAuthRequestSigner(
            `${firstKeyPair.privateKeyPem},${secondKeyPair.privateKeyPem.replaceAll('\n', '\\n')}`
        )
        const url = 'https://cdn.example.com/image.png'

        const headers = signer.headersForGet(url)

        expectSignedHeadersToVerify('GET', url, headers, firstKeyPair.publicKey, 'sig1')
        expect(headers['signature-input']).not.toContain(keyId(secondKeyPair.publicKey))
        expect(headers.signature).not.toContain('sig2=')
    })

    it.each([
        ['an empty value', '', 'must contain at least one'],
        ['a malformed key', 'not a PEM', 'entry 1 could not be loaded'],
        [
            'a malformed non-active key',
            `${generateEd25519KeyPair().privateKeyPem},not a PEM`,
            'entry 2 could not be loaded',
        ],
        [
            'a non-Ed25519 key',
            generateKeyPairSync('rsa', { modulusLength: 2048 })
                .privateKey.export({ format: 'pem', type: 'pkcs8' })
                .toString(),
            'entry 1 is not an Ed25519 private key',
        ],
    ])('rejects %s', (_name, privateKeyPems, expectedError) => {
        expect(() => createWebBotAuthRequestSigner(privateKeyPems)).toThrow(expectedError)
    })
})
