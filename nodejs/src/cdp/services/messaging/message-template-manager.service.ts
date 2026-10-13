import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'

export type MessageTemplate = {
    id: string
    team_id: number
    name: string
    message_category_id: string | null
    email: {
        subject?: string
        preheader?: string
        text?: string
        html?: string
    }
}

type MessageTemplateRow = {
    id: string
    team_id: number
    name: string
    message_category_id: string | null
    content: { email?: MessageTemplate['email'] } | null
}

/**
 * Loads the email templates that transactional sends reference by id, so a queued job carries the id
 * and not the template HTML. Django publishes `reload-message-templates` when a template changes.
 */
export class MessageTemplateManagerService {
    private lazyLoader: LazyLoader<MessageTemplate>

    constructor(
        private postgres: PostgresRouter,
        private pubSub: PubSub
    ) {
        this.lazyLoader = new LazyLoader({
            name: 'message_template_manager',
            loader: async (ids) => await this.fetchTemplates(ids),
        })
        this.pubSub.on<{ templateIds: string[] }>('reload-message-templates', (message) => {
            logger.debug('⚡', '[PubSub] Reloading message templates!', { templateIds: message.templateIds })
            this.lazyLoader.markForRefresh(message.templateIds)
        })
    }

    public async get(id: string): Promise<MessageTemplate | null> {
        return (await this.lazyLoader.get(id)) ?? null
    }

    private async fetchTemplates(ids: string[]): Promise<Record<string, MessageTemplate | undefined>> {
        const response = await this.postgres.query<MessageTemplateRow>(
            PostgresUse.COMMON_READ,
            `SELECT id, team_id, name, message_category_id, content
             FROM posthog_messagetemplate
             WHERE id = ANY($1) AND deleted = false AND type = 'email'`,
            [ids],
            'fetchMessageTemplates'
        )

        return response.rows.reduce<Record<string, MessageTemplate | undefined>>((acc, row) => {
            acc[row.id] = {
                id: row.id,
                team_id: row.team_id,
                name: row.name,
                message_category_id: row.message_category_id,
                email: row.content?.email ?? {},
            }
            return acc
        }, {})
    }
}
