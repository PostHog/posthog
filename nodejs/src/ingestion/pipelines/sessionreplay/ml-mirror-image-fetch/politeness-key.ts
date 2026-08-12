import { getDomain } from 'tldts'

/**
 * The politeness unit for a host: the registrable domain, or the host itself when it has none.
 *
 * This must return what `politeness_key` in `rust/replay-anonymizer/src/url_policy.rs` returns for
 * the same host. That function sets the Kafka key of the fetch topic, so a host reaching this lane
 * through a redirect has to land in the same budget as the same host reaching it through the key.
 * Two answers for one host means one site is rate limited under two separate allowances.
 *
 * `allowPrivateDomains` is what makes them agree. Without it `d111.cloudfront.net`,
 * `bucket.s3.amazonaws.com`, `user.github.io` and `myapp.vercel.app` all collapse into their
 * provider, so unrelated tenants share one budget and one breaker.
 *
 * An IP literal has no registrable domain and comes back unchanged, because the address is the
 * operator.
 */
export function politenessKey(host: string): string {
    return getDomain(host, { allowPrivateDomains: true }) ?? host
}
