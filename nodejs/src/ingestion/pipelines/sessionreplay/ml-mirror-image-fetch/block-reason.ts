export type ImageFetchBlockReason =
    | 'domain_concurrency'
    | 'request_capacity'
    | 'origin_crawl_delay'
    | 'registrable_domain_rate'
    | 'retry_after'
    | 'transient_backoff'
    | 'unknown_backoff'
    | 'configuration_unreachable'
    | 'configuration_deferred'
    | 'breaker_open'
    | 'connection_limit'
    | 'origin_map_full'
    | 'registrable_domain_map_full'
    | 'pass_deadline'
    | 'request_deadline'

const IMAGE_FETCH_BLOCK_REASONS = new Set<ImageFetchBlockReason>([
    'domain_concurrency',
    'request_capacity',
    'origin_crawl_delay',
    'registrable_domain_rate',
    'retry_after',
    'transient_backoff',
    'unknown_backoff',
    'configuration_unreachable',
    'configuration_deferred',
    'breaker_open',
    'connection_limit',
    'origin_map_full',
    'registrable_domain_map_full',
    'pass_deadline',
    'request_deadline',
])

export function isImageFetchBlockReason(value: unknown): value is ImageFetchBlockReason {
    return typeof value === 'string' && IMAGE_FETCH_BLOCK_REASONS.has(value as ImageFetchBlockReason)
}
