import { kea, path, props, selectors } from 'kea'

import { Scene } from 'scenes/sceneTypes'

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
                    key: Scene.Site,
                    name: `Site`,
                    iconType: 'heatmap',
                },
                {
                    key: [Scene.Site, url],
                    name: url,
                    iconType: 'heatmap',
                },
            ],
        ],
    }),
])
