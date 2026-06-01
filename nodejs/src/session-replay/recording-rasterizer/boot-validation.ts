import { isProdEnv } from '../../utils/env-utils'

/**
 * Each rule is `MAP <hostname pattern> <host>[:<port>]` or
 * `EXCLUDE <hostname pattern>`. Hostname pattern characters are restricted to
 * what's needed for real hostname routing: alphanumerics, `.`, `-`, `*`,
 * IPv4 separators, and `:` for port. Spaces separate the verb from operands,
 * commas separate rules.
 *
 * This regex is intentionally strict — `--host-resolver-rules` accepts more
 * exotic forms but we don't use them, and forgiving the parse makes it harder
 * to spot a misconfiguration that silently redirects a hostname.
 */
const HOST_RESOLVER_TOKEN = /^[\w*.\-]+(?::\d+)?$/
const HOST_RESOLVER_RULE = /^(?:MAP\s+\S+\s+\S+|EXCLUDE\s+\S+)$/

function validateHostResolverRules(raw: string): void {
    const rules = raw.split(',').map((r) => r.trim())
    for (const rule of rules) {
        if (!HOST_RESOLVER_RULE.test(rule)) {
            throw new Error(`CHROME_HOST_RESOLVER_RULES rule does not match expected form: ${JSON.stringify(rule)}`)
        }
        const parts = rule.split(/\s+/)
        // Verb is parts[0]; remaining parts are hostnames or hostname:port.
        for (const operand of parts.slice(1)) {
            if (!HOST_RESOLVER_TOKEN.test(operand)) {
                throw new Error(
                    `CHROME_HOST_RESOLVER_RULES contains an unsupported character in ${JSON.stringify(operand)}`
                )
            }
        }
    }
}

/**
 * Refuse to start in production with debug knobs that loosen browser
 * security. These flags exist for local development and CI; if they ever
 * land on a prod rasterizer pod it's a config mistake we want to surface
 * loudly, not silently degrade.
 *
 * In non-production environments the flags are validated for format but
 * accepted.
 */
export function validateBootEnvironment(): void {
    const hostResolverRules = process.env.CHROME_HOST_RESOLVER_RULES
    if (hostResolverRules) {
        validateHostResolverRules(hostResolverRules)
    }

    if (!isProdEnv()) {
        return
    }

    if (process.env.DISABLE_BROWSER_SECURITY === '1') {
        throw new Error(
            'DISABLE_BROWSER_SECURITY is set in a production environment. This flag removes Chrome cross-origin protections and must not be used in prod. Unset it or run with NODE_ENV != production.'
        )
    }

    if (hostResolverRules) {
        throw new Error(
            'CHROME_HOST_RESOLVER_RULES is set in a production environment. This flag can silently redirect any hostname Chrome resolves and is only safe for local development. Unset it or run with NODE_ENV != production.'
        )
    }
}
