import { isProdEnv, stringToBoolean } from '~/common/utils/env-utils'

import { createLogger } from './logger'

const log = createLogger()

// Egress containment for attacker-controlled recording content rests entirely on routing Chrome
// (and the S3 client) through the smokescreen proxy. Both consumers previously resolved the proxy
// env vars independently with subtly different logic, which is the drift that caused the STS 407
// outage. This is the single source of truth, and in production it fails closed: a missing proxy
// URL refuses to start rather than silently letting Chrome dial internal endpoints directly.
export function resolveEgressProxyUrl(): string | null {
    const upstream =
        process.env.HTTPS_PROXY || process.env.HTTP_PROXY || process.env.https_proxy || process.env.http_proxy
    const killed = stringToBoolean((process.env.RASTERIZER_USE_PROXY ?? '').trim(), true) === false

    if (killed) {
        log.warn(
            { RASTERIZER_USE_PROXY: process.env.RASTERIZER_USE_PROXY },
            'RASTERIZER_USE_PROXY disables the egress proxy — chrome and s3 will dial direct'
        )
        return null
    }
    if (!upstream) {
        if (isProdEnv()) {
            throw new Error(
                'No egress proxy configured (HTTPS_PROXY/HTTP_PROXY): recordings are untrusted content, so ' +
                    'production refuses to run without egress containment. Set the proxy URL, or set ' +
                    'RASTERIZER_USE_PROXY=false to explicitly accept direct egress.'
            )
        }
        return null
    }
    return upstream
}
