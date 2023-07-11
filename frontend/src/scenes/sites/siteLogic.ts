import { kea, props, selectors, path } from 'kea'
import { Breadcrumb } from '~/types'

import type { siteLogicType } from './siteLogicType'

export interface SiteLogicProps {
    url: string
}

export const siteLogic = kea<siteLogicType>([
    path(['scenes', 'sites', 'siteLogic']),
    props({} as SiteLogicProps),
    selectors({
        breadcrumbs: [
            (_, p) => [p.url],
            (url): Breadcrumb[] => [
                {
                    name: `Site`,
                },
                {
                    name: url,
                },
            ],
        ],
    }),
])
