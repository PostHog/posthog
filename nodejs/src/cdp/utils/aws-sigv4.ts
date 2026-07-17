import { createHash, createHmac } from 'node:crypto'

import { CyclotronInvocationQueueParametersFetchAwsSigV4Type } from '~/cdp/schema/cyclotron'

import { HogFunctionType } from '../types'

export type AwsSigV4Credentials = {
    service: string
    region: string
    access_key_id: string
    secret_access_key: string
    session_token?: string
}

export type ResolvedAwsSigV4Credentials = { ok: true; credentials: AwsSigV4Credentials } | { ok: false; error: string }

export type SignAwsRequestArgs = {
    method: string
    url: string
    body?: string | null
    headers?: Record<string, string>
    credentials: AwsSigV4Credentials
    now?: Date
}

const ALGORITHM = 'AWS4-HMAC-SHA256'

// Headers that are signing artifacts — must always be rebuilt, never inherited
// from a previous attempt's queue payload.
const SIGNING_HEADERS = new Set(['authorization', 'x-amz-date', 'x-amz-content-sha256', 'x-amz-security-token'])

function sha256Hex(input: string): string {
    return createHash('sha256').update(input).digest('hex')
}

function hmac(key: Buffer | string, data: string): Buffer {
    return createHmac('sha256', key).update(data).digest()
}

function deriveSigningKey(secret: string, date: string, region: string, service: string): Buffer {
    const kDate = hmac(`AWS4${secret}`, date)
    const kRegion = hmac(kDate, region)
    const kService = hmac(kRegion, service)
    return hmac(kService, 'aws4_request')
}

// AWS canonical URI encoding: encodeURIComponent + reserved-char fixes.
// Unreserved per RFC 3986: A-Z a-z 0-9 - _ . ~. Slashes are kept as path separators.
function awsUriEncode(input: string, encodeSlash: boolean): string {
    let out = ''
    for (const ch of input) {
        if (/[A-Za-z0-9\-_.~]/.test(ch)) {
            out += ch
        } else if (ch === '/' && !encodeSlash) {
            out += ch
        } else {
            out += encodeURIComponent(ch).replace(/[!'()*]/g, (c) => '%' + c.charCodeAt(0).toString(16).toUpperCase())
        }
    }
    return out
}

// Decode a single percent-encoded query-string segment. Bare `%` or `%X` (no
// second hex digit) makes `decodeURIComponent` throw URIError; AWS canonical
// encoding still needs to produce *some* string, so we treat malformed input
// as opaque and re-encode it as-is. Callers must not surface URIError from a
// signing path — a thrown error here fails the entire fetch instead of letting
// the upstream return a normal 400.
function safeDecodeQuerySegment(s: string): string {
    try {
        return decodeURIComponent(s)
    } catch {
        return s
    }
}

function canonicalQueryString(search: string): string {
    if (!search || search === '?') {
        return ''
    }
    const params: [string, string][] = []
    for (const part of search.replace(/^\?/, '').split('&')) {
        if (!part) {
            continue
        }
        const eq = part.indexOf('=')
        const k = eq === -1 ? part : part.slice(0, eq)
        const v = eq === -1 ? '' : part.slice(eq + 1)
        params.push([awsUriEncode(safeDecodeQuerySegment(k), true), awsUriEncode(safeDecodeQuerySegment(v), true)])
    }
    params.sort(([a1, a2], [b1, b2]) => (a1 < b1 ? -1 : a1 > b1 ? 1 : a2 < b2 ? -1 : a2 > b2 ? 1 : 0))
    return params.map(([k, v]) => `${k}=${v}`).join('&')
}

function formatAmzDate(d: Date): { amzDate: string; date: string } {
    const pad = (n: number, w = 2) => n.toString().padStart(w, '0')
    const yyyy = d.getUTCFullYear().toString()
    const mm = pad(d.getUTCMonth() + 1)
    const dd = pad(d.getUTCDate())
    const hh = pad(d.getUTCHours())
    const mi = pad(d.getUTCMinutes())
    const ss = pad(d.getUTCSeconds())
    return { amzDate: `${yyyy}${mm}${dd}T${hh}${mi}${ss}Z`, date: `${yyyy}${mm}${dd}` }
}

/**
 * Signs an HTTP request with AWS Signature Version 4.
 *
 * Returns a fresh headers object that callers should USE INSTEAD OF any prior
 * `Authorization` / `X-Amz-Date` headers — those are signing artifacts that
 * become invalid on every retry, so we strip any inherited values before
 * recomputing them.
 *
 * The signature is bound to `now` (defaults to current wall clock). AWS rejects
 * signatures older than ~5 minutes, so this function must be called immediately
 * before each fetch attempt — not at request-construction time.
 */
export function signAwsRequest({
    method,
    url,
    body,
    headers,
    credentials,
    now,
}: SignAwsRequestArgs): Record<string, string> {
    const parsed = new URL(url)
    // Read time via `Date.now()` so test seams that mock `Date.now` (the standard
    // PostHog jest pattern) flow through to the signature timestamp.
    const { amzDate, date } = formatAmzDate(now ?? new Date(Date.now()))

    const baseHeaders: Record<string, string> = {}
    for (const [k, v] of Object.entries(headers ?? {})) {
        if (!SIGNING_HEADERS.has(k.toLowerCase())) {
            baseHeaders[k] = v
        }
    }
    baseHeaders['Host'] = parsed.host
    baseHeaders['X-Amz-Date'] = amzDate
    if (credentials.session_token) {
        baseHeaders['X-Amz-Security-Token'] = credentials.session_token
    }

    const sortedHeaderEntries = Object.entries(baseHeaders)
        .map(([k, v]) => [k.toLowerCase(), v.trim().replace(/\s+/g, ' ')] as [string, string])
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))

    const canonicalHeaders = sortedHeaderEntries.map(([k, v]) => `${k}:${v}`).join('\n') + '\n'
    const signedHeaders = sortedHeaderEntries.map(([k]) => k).join(';')

    const path = parsed.pathname || '/'
    const canonicalRequest = [
        method.toUpperCase(),
        awsUriEncode(path, false),
        canonicalQueryString(parsed.search),
        canonicalHeaders,
        signedHeaders,
        sha256Hex(body ?? ''),
    ].join('\n')

    const credentialScope = `${date}/${credentials.region}/${credentials.service}/aws4_request`
    const stringToSign = [ALGORITHM, amzDate, credentialScope, sha256Hex(canonicalRequest)].join('\n')

    const signingKey = deriveSigningKey(credentials.secret_access_key, date, credentials.region, credentials.service)
    const signature = createHmac('sha256', signingKey).update(stringToSign).digest('hex')

    const authorization =
        `${ALGORITHM} Credential=${credentials.access_key_id}/${credentialScope}, ` +
        `SignedHeaders=${signedHeaders}, ` +
        `Signature=${signature}`

    return {
        ...baseHeaders,
        Authorization: authorization,
    }
}

/**
 * Resolves the AWS credentials referenced by an `aws_sigv4` queue payload from a
 * HogFunction's inputs.
 *
 * `secret: true` HogFunction inputs land in `encrypted_inputs` after Django's
 * `move_secret_inputs` runs on save (and the Node manager decrypts that field in
 * memory). The Kinesis credential inputs are flagged `secret: true`, so check
 * `encrypted_inputs` first; fall back to `inputs` for the unusual case of a
 * non-secret credential.
 *
 * Returns a tagged union so callers can fail closed on missing inputs without
 * shipping an unsigned request to AWS. The error message lists the input keys
 * that could not be resolved so the failure is debuggable from logs alone.
 */
export function resolveAwsSigV4Credentials(
    sigv4: CyclotronInvocationQueueParametersFetchAwsSigV4Type,
    hogFunction: Pick<HogFunctionType, 'inputs' | 'encrypted_inputs'>
): ResolvedAwsSigV4Credentials {
    const lookup = (key: string): unknown =>
        hogFunction.encrypted_inputs?.[key]?.value ?? hogFunction.inputs?.[key]?.value

    const accessKeyId = lookup(sigv4.access_key_id_input)
    const secretAccessKey = lookup(sigv4.secret_access_key_input)
    const sessionToken = sigv4.session_token_input ? lookup(sigv4.session_token_input) : undefined

    const missing: string[] = []
    if (typeof accessKeyId !== 'string') {
        missing.push(sigv4.access_key_id_input)
    }
    if (typeof secretAccessKey !== 'string') {
        missing.push(sigv4.secret_access_key_input)
    }

    if (missing.length > 0) {
        return {
            ok: false,
            error: `AWS SigV4 signing failed: input(s) ${missing.join(', ')} not found on hog function or not a string. Refusing to send an unsigned request to AWS.`,
        }
    }

    return {
        ok: true,
        credentials: {
            service: sigv4.service,
            region: sigv4.region,
            access_key_id: accessKeyId as string,
            secret_access_key: secretAccessKey as string,
            session_token: typeof sessionToken === 'string' ? sessionToken : undefined,
        },
    }
}
