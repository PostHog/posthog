import type { CdpConfig } from '@posthog/hog-engine/cdp/config'
import type { InternalLogsProducerConfig } from '@posthog/node-common/logs/internal-logs-producer'
import type { CommonConfig } from '@posthog/node-common/types'

export * from '@posthog/node-common/types'

// The engine reads the internal logs settings and the sources switch from the host's config when it runs
// transformations, so the ingestion services carry those alongside the common settings.
export interface PluginsServerConfig
    extends CommonConfig,
        InternalLogsProducerConfig,
        Pick<CdpConfig, 'CDP_INTERNAL_LOGS_SOURCES'> {}
