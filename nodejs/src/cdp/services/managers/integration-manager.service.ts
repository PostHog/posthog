import { Counter } from 'prom-client'

import { IntegrationType } from '~/cdp/types'
import { IntegrationIdInput, IntegrationReference, toIntegrationReference } from '~/cdp/utils/integration-reference'
import { DEFAULT_LOADER_RETRY, LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'

import { IntegrationDecryptFailure, IntegrationSource, IntegrationSourceRecord } from './integration-source'

const INTEGRATION_CACHE_TTL_MS = 60_000

const integrationDecryptFailures = new Counter({
    name: 'cdp_integration_decrypt_failures_total',
    help: 'Integration fields that a source loaded but could not decrypt. The field keeps its ciphertext.',
    labelNames: ['source', 'kind', 'reason'],
})

export class IntegrationManagerService {
    private lazyLoader: LazyLoader<IntegrationSourceRecord>

    constructor(
        private pubSub: PubSub,
        private source: IntegrationSource
    ) {
        this.lazyLoader = new LazyLoader({
            name: 'integration_manager',
            loader: async (references) => await this.loadIntegrations(references),
            loaderRetry: DEFAULT_LOADER_RETRY,
            refreshAgeMs: INTEGRATION_CACHE_TTL_MS,
            expiresAt: (record) => record.expiresAt,
        })
        this.pubSub.on<{ integrationIds: IntegrationIdInput[] }>('reload-integrations', (message) => {
            logger.debug('⚡', '[PubSub] Reloading integrations!', { integrationIds: message.integrationIds })
            this.onIntegrationsReloaded(message.integrationIds)
        })
    }

    /** Returns null for a value that is not a valid reference, and for a reference with no row. */
    public async get(id: IntegrationIdInput): Promise<IntegrationType | null> {
        const reference = toIntegrationReference(id)
        if (reference === null) {
            return null
        }
        return (await this.lazyLoader.get(reference))?.integration ?? null
    }

    /**
     * Keys the result by canonical reference. A legacy id gives the same key as a number or a
     * string, so callers can index with the number they hold. Invalid values have no key.
     */
    public async getMany(ids: IntegrationIdInput[]): Promise<Record<IntegrationReference, IntegrationType | null>> {
        const references = toReferences(ids)
        const records = await this.lazyLoader.getMany(references)
        const result: Record<IntegrationReference, IntegrationType | null> = {}
        for (const reference of references) {
            result[reference] = records[reference]?.integration ?? null
        }
        return result
    }

    public async getDecryptFailures(
        ids: IntegrationIdInput[]
    ): Promise<Record<IntegrationReference, IntegrationDecryptFailure[]>> {
        const references = toReferences(ids)
        const records = await this.lazyLoader.getMany(references)
        const result: Record<IntegrationReference, IntegrationDecryptFailure[]> = {}
        for (const reference of references) {
            result[reference] = records[reference]?.decryptFailures ?? []
        }
        return result
    }

    private onIntegrationsReloaded(integrationIds: IntegrationIdInput[]): void {
        this.lazyLoader.markForRefresh(toReferences(integrationIds))
    }

    private async loadIntegrations(
        references: IntegrationReference[]
    ): Promise<Record<IntegrationReference, IntegrationSourceRecord>> {
        logger.info('[IntegrationManager]', 'Loading integrations', { references, source: this.source.name })

        const records = await this.source.load(references)
        for (const record of Object.values(records)) {
            this.reportDecryptFailures(record)
        }
        return records
    }

    private reportDecryptFailures(record: IntegrationSourceRecord): void {
        if (record.decryptFailures.length === 0) {
            return
        }
        const { kind, team_id } = record.integration
        for (const failure of record.decryptFailures) {
            integrationDecryptFailures.labels({ source: this.source.name, kind, reason: failure.reason }).inc()
        }
        // Only field paths, never values: a value that did not decrypt can still be a secret.
        logger.warn('[IntegrationManager]', 'Integration has fields that did not decrypt', {
            reference: record.reference,
            teamId: team_id,
            kind,
            source: this.source.name,
            failures: record.decryptFailures,
        })
    }
}

function toReferences(ids: IntegrationIdInput[]): IntegrationReference[] {
    const references = new Set<IntegrationReference>()
    for (const id of ids) {
        const reference = toIntegrationReference(id)
        if (reference !== null) {
            references.add(reference)
        }
    }
    return Array.from(references)
}
