import { FileSystemImport } from '~/queries/schema/schema-general'

import { osCatalogApps, osStoreSections } from './osAppCatalog'

const product = (path: string, extra: Partial<FileSystemImport> = {}): FileSystemImport => ({
    path,
    type: 'product',
    href: `/${path.toLowerCase().replace(/ /g, '-')}`,
    ...extra,
})

describe('osAppCatalog', () => {
    it('hides apps whose feature flag is off, and shows them once it is on', () => {
        const products = [product('Links', { flag: 'links', category: 'Unreleased', tags: ['alpha'] })]

        expect(osCatalogApps(products, {}).map((app) => app.name)).toEqual([])
        expect(osCatalogApps(products, { links: true }).map((app) => app.name)).toEqual(['Links'])
    })

    it('leaves out apps without a link', () => {
        const products = [product('Notebooks'), product('No link', { href: undefined }), product('Surveys')]

        expect(osCatalogApps(products, {}).map((app) => app.key)).toEqual(['Notebooks', 'Surveys'])
    })

    it('groups released apps by job, then puts beta and labs apps in their own sections', () => {
        const products = [
            product('Surveys'),
            product('Session replay'),
            product('Feature flags'),
            product('Heatmaps', { tags: ['beta'] }),
            product('Metrics', { tags: ['alpha'] }),
            product('Pulse', { category: 'Unreleased', flag: 'pulse' }),
            product('Something new', { category: 'Tools' }),
        ]

        const sections = osStoreSections(osCatalogApps(products, { pulse: true }))

        expect(sections.map(({ title, apps }) => [title, apps.map((app) => app.name)])).toEqual([
            ['Watch and ask users', ['Session replay', 'Surveys']],
            ['Ship and test', ['Feature flags']],
            ['More apps', ['Something new']],
            ['Beta', ['Heatmaps']],
            ['Labs', ['Metrics', 'Pulse']],
        ])
    })
})
