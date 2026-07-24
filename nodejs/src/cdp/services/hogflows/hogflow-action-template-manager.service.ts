import { CyclotronInputMappingType, CyclotronInputType } from '~/cdp/schema/cyclotron'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { PubSub } from '~/common/utils/pubsub'
import { Team } from '~/types'

import { EncryptedFields } from '../../utils/encryption-utils'

// Keep in sync with products/workflows/backend/models/hog_flow/hog_flow_action_template.py
export type HogFlowActionTemplate = {
    id: string
    team_id: number
    name: string
    template_id: string
    inputs: Record<string, CyclotronInputType>
    encrypted_inputs: Record<string, CyclotronInputType> | string | null
    mappings: CyclotronInputMappingType[] | null
}

export class HogFlowActionTemplateManagerService {
    private lazyLoader: LazyLoader<HogFlowActionTemplate>

    constructor(
        private postgres: PostgresRouter,
        private pubSub: PubSub,
        private encryptedFields: EncryptedFields
    ) {
        this.lazyLoader = new LazyLoader({
            name: 'hog_flow_action_template_manager',
            // The reload-hog-flow-action-templates pub/sub below is the primary invalidation; these
            // ages bound how stale a worker can run when it misses the publish (pod restart, Redis
            // blip). Template edits are expected to reach linked workflows quickly, so a hot template
            // self-heals within ~30s via a non-blocking background refresh, with a 2 minute hard cap.
            refreshAgeMs: 2 * 60 * 1000,
            refreshBackgroundAgeMs: 30 * 1000,
            // Absorb transient Postgres blips inside a single load attempt so failed background
            // refreshes don't re-fire at caller QPS and hard-cap refreshes don't fail the batch.
            loaderRetry: { retryIntervalMs: 250, retryJitterMs: 250, maxElapsedMs: 5000 },
            loader: async (ids) => await this.fetchActionTemplates(ids),
        })

        this.pubSub.on<{ teamId: Team['id']; templateIds: string[] }>('reload-hog-flow-action-templates', (message) => {
            const { teamId, templateIds } = message
            logger.debug('⚡', '[PubSub] Reloading hog flow action templates!', { teamId, templateIds })
            this.lazyLoader.markForRefresh(templateIds)
        })
    }

    public async getHogFlowActionTemplate(id: string): Promise<HogFlowActionTemplate | null> {
        return (await this.lazyLoader.get(id)) ?? null
    }

    private async fetchActionTemplates(ids: string[]): Promise<Record<string, HogFlowActionTemplate | undefined>> {
        logger.debug('[HogFlowActionTemplateManager]', 'Fetching action templates', { ids })

        const response = await this.postgres.query<HogFlowActionTemplate>(
            PostgresUse.COMMON_READ,
            `SELECT id, team_id, name, template_id, inputs, encrypted_inputs, mappings
            FROM posthog_hogflowactiontemplate
            WHERE id = ANY($1) AND deleted = FALSE`,
            [ids],
            'fetchHogFlowActionTemplates'
        )

        return response.rows.reduce<Record<string, HogFlowActionTemplate | undefined>>((acc, item) => {
            this.decryptInputs(item)
            acc[item.id] = item
            return acc
        }, {})
    }

    private decryptInputs(item: HogFlowActionTemplate): void {
        const encryptedInputs = item.encrypted_inputs

        // The sql lib can sometimes return an empty object instead of an empty array
        if (encryptedInputs && typeof encryptedInputs === 'object' && !Array.isArray(encryptedInputs)) {
            return
        }

        if (typeof encryptedInputs === 'string') {
            try {
                const decrypted = this.encryptedFields.decrypt(encryptedInputs)
                if (decrypted) {
                    item.encrypted_inputs = parseJSON(decrypted)
                }
            } catch (error) {
                if (encryptedInputs) {
                    logger.warn(
                        '[HogFlowActionTemplateManager]',
                        'Could not parse encrypted inputs - preserving original value',
                        {
                            error: error instanceof Error ? error.message : 'Unknown error',
                        }
                    )
                    captureException(error)
                }
            }
        }
        // For any other case (null, undefined, unexpected types), leave as-is
    }
}
