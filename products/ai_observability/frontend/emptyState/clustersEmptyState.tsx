import * as scientistPng from '@posthog/brand/hoggies/png/scientist'
import { IconScatter } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { ClustersSetupActions } from '../clusters/ClustersSetupActions'
import { ClustersPreview } from './ClustersPreview'
import { clustersSetupLogic } from './clustersSetupLogic'

const HedgehogScientist = pngHoggie(scientistPng)

export const clustersEmptyState: SceneProductEmptyState = {
    statusLogic: clustersSetupLogic,
    config: {
        productKey: ProductKey.LLM_CLUSTERS,
        productName: 'Clusters',
        skippable: false,
        icon: <IconScatter />,
        accentColor: 'var(--color-product-llm-clusters-light)',
        accentColorDark: 'var(--color-product-llm-analytics-dark)',
        hedgehog: HedgehogScientist,
        text: {
            'needs-setup': {
                headline: 'Find the patterns in how people use your AI',
                lead: 'Group similar traces, generations, and evaluations to see what people ask for and where things go wrong.',
            },
            'waiting-for-data': {
                headline: 'Clustering is enabled',
                lead: 'Your scheduled jobs will look for groups as new data arrives. Each job needs at least 10 eligible items. Review your jobs and their filters while you wait.',
            },
        },
        PrimaryAction: ClustersSetupActions,
        docsUrl: 'https://posthog.com/docs/ai-observability/clusters',
        manualSetupUrl: 'https://posthog.com/docs/ai-observability/installation',
        previewLabel: 'Example: conversations grouped by topic',
        Preview: ClustersPreview,
    },
}
