import { Hub } from '../../../types'
import { PostgresUse } from '../../../utils/db/postgres'
import { LazyLoader } from '../../../utils/lazy-loader'
import { logger } from '../../../utils/logger'

export type LinkType = {
    id: string
    team_id: number
    redirect_url: string
    short_link_domain: string
    short_code: string
    description: string | null
    created_at: string
    updated_at: string
    hog_function: string
}

const LINK_FIELDS = [
    'id',
    'team_id',
    'redirect_url',
    'short_link_domain',
    'short_code',
    'description',
    'created_at',
    'updated_at',
    'hog_function',
]

const toKey = (shortLinkDomain: string, shortCode: string): string => `${shortLinkDomain}|_${shortCode}`

const fromKey = (key: string): { shortLinkDomain: string; shortCode: string } => {
    const [shortLinkDomain, shortCode] = key.split('|_', 2)
    return { shortLinkDomain, shortCode }
}

export class LinkManagerService {
    private lazyLoader: LazyLoader<LinkType>

    constructor(private hub: Hub) {
        this.lazyLoader = new LazyLoader({
            name: 'link_manager',
            loader: async (ids) => await this.fetchLinks(ids),
        })
    }

    public async getLink(shortLinkDomain: string, shortCode: string): Promise<LinkType | null> {
        const key = toKey(shortLinkDomain, shortCode)
        return (await this.lazyLoader.get(key)) ?? null
    }

    public async getLinks(
        links: Array<{ shortLinkDomain: string; shortCode: string }>
    ): Promise<Record<string, LinkType | null>> {
        const keys = links.map((link) => toKey(link.shortLinkDomain, link.shortCode))
        const results = await this.lazyLoader.getMany(keys)
        return results
    }

    public clear(): void {
        this.lazyLoader.clear()
    }

    private async fetchLinks(keys: string[]): Promise<Record<string, LinkType | undefined>> {
        logger.debug('[LinkManager]', 'Fetching links', { keys })

        const linkArgs = keys.map(fromKey)

        // Build the WHERE clause for multiple short_link_domain, short_code pairs
        const conditions = linkArgs
            .map((_, index) => {
                const domainParam = index * 2 + 1
                const codeParam = index * 2 + 2
                // NOTE: We have a unique index on (short_link_domain, short_code) so this should be efficient
                return `(short_link_domain = $${domainParam} AND short_code = $${codeParam})`
            })
            .join(' OR ')

        const queryString = `SELECT ${LINK_FIELDS.join(', ')}
            FROM posthog_link
            WHERE ${conditions}`

        // Flatten the parameters: [domain1, code1, domain2, code2, ...]
        const params = linkArgs.flatMap((link) => [link.shortLinkDomain, link.shortCode])

        const response = await this.hub.postgres.query<LinkType>(
            PostgresUse.COMMON_READ,
            queryString,
            params,
            'fetchLinks'
        )

        const linkRows = response.rows

        // Map results back to the original keys
        const result: Record<string, LinkType | undefined> = {}
        for (const row of linkRows) {
            const key = toKey(row.short_link_domain, row.short_code)
            result[key] = row
        }

        return result
    }
}
