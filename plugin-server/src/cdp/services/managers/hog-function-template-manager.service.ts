import { Hub } from '../../../types'
import { PostgresUse } from '../../../utils/db/postgres'
import { LazyLoader } from '../../../utils/lazy-loader'
import { logger } from '../../../utils/logger'
import { DBHogFunctionTemplate } from '../../types'

const HOG_FUNCTION_TEMPLATE_FIELDS = ['id', 'template_id', 'sha', 'name', 'inputs_schema', 'bytecode', 'type', 'free']

export class HogFunctionTemplateManagerService {
    private lazyLoader: LazyLoader<DBHogFunctionTemplate>
    // private started: boolean

    constructor(private hub: Hub) {
        // this.started = false

        this.lazyLoader = new LazyLoader({
            name: 'hog_function_template_manager',
            loader: async (ids) => await this.fetchHogFunctionTemplates(ids),
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

    // NOTE: Currently this essentially loads the "latest" template each time. We may need to swap this to using a specific version
    private async fetchHogFunctionTemplates(ids: string[]): Promise<Record<string, DBHogFunctionTemplate | undefined>> {
        logger.info('[HogFunctionTemplateManager]', 'Fetching hog function templates', { ids })

        const response = await this.hub.postgres.query<DBHogFunctionTemplate>(
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
