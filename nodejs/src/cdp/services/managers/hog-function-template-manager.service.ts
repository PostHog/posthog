import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'

import { DBHogFunctionTemplate } from '../../types'

const HOG_FUNCTION_TEMPLATE_FIELDS = ['id', 'template_id', 'sha', 'name', 'inputs_schema', 'bytecode', 'type', 'free']

export class HogFunctionTemplateManagerService {
    private lazyLoader: LazyLoader<DBHogFunctionTemplate>
    private versionsLoader: LazyLoader<DBHogFunctionTemplate[]>
    // private started: boolean

    constructor(private postgres: PostgresRouter) {
        // this.started = false

        this.lazyLoader = new LazyLoader({
            name: 'hog_function_template_manager',
            loader: async (ids) => await this.fetchHogFunctionTemplates(ids),
        })
        this.versionsLoader = new LazyLoader({
            name: 'hog_function_template_versions_manager',
            loader: async (ids) => await this.fetchHogFunctionTemplateVersions(ids),
        })
    }

    // public async start(): Promise<void> {
    //     // TRICKY - when running with individual capabilities, this won't run twice but locally or as a complete service it will...
    //     if (this.started) {
    //         return
    //     }
    //     this.started = true
    // }

    // public async stop(): Promise<void> {}

    public async getHogFunctionTemplate(id: DBHogFunctionTemplate['id']): Promise<DBHogFunctionTemplate | null> {
        return (await this.lazyLoader.get(id)) ?? null
    }

    public async getHogFunctionTemplates(
        ids: DBHogFunctionTemplate['id'][]
    ): Promise<Record<DBHogFunctionTemplate['id'], DBHogFunctionTemplate | null>> {
        return await this.lazyLoader.getMany(ids)
    }

    /** Every stored version of a template. A function keeps the bytecode it was saved with, so a check against the template has to accept older versions too. */
    public async getHogFunctionTemplateVersions(templateId: string): Promise<DBHogFunctionTemplate[]> {
        return (await this.versionsLoader.get(templateId)) ?? []
    }

    private async fetchHogFunctionTemplateVersions(ids: string[]): Promise<Record<string, DBHogFunctionTemplate[]>> {
        const response = await this.postgres.query<DBHogFunctionTemplate>(
            PostgresUse.COMMON_READ,
            `SELECT ${HOG_FUNCTION_TEMPLATE_FIELDS.join(
                ', '
            )} FROM posthog_hogfunctiontemplate WHERE template_id = ANY($1)`,
            [ids],
            'fetchHogFunctionTemplateVersions'
        )
        return response.rows.reduce<Record<string, DBHogFunctionTemplate[]>>((acc, template) => {
            ;(acc[template.template_id] ??= []).push(template)
            return acc
        }, {})
    }

    // NOTE: Currently this essentially loads the "latest" template each time. We may need to swap this to using a specific version
    private async fetchHogFunctionTemplates(ids: string[]): Promise<Record<string, DBHogFunctionTemplate | undefined>> {
        logger.info('[HogFunctionTemplateManager]', 'Fetching hog function templates', { ids })

        const response = await this.postgres.query<DBHogFunctionTemplate>(
            PostgresUse.COMMON_READ,
            `SELECT ${HOG_FUNCTION_TEMPLATE_FIELDS.join(
                ', '
            )} FROM posthog_hogfunctiontemplate WHERE template_id = ANY($1)`,
            [ids],
            'fetchHogFunctionTemplates'
        )

        const hogFunctionTemplates = response.rows

        return hogFunctionTemplates.reduce<Record<string, DBHogFunctionTemplate | undefined>>(
            (acc, hogFunctionTemplate) => {
                acc[hogFunctionTemplate.template_id] = hogFunctionTemplate
                return acc
            },
            {}
        )
    }
}
