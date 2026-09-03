import * as scientistPng from '@posthog/brand/hoggies/png/scientist'
import { IconScatter } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { ClustersPreview } from './ClustersPreview'
import { clustersSetupLogic } from './clustersSetupLogic'

const HedgehogScientist = pngHoggie(scientistPng)

export const clustersEmptyState: SceneProductEmptyState = {
    statusLogic: clustersSetupLogic,
    config: {
        productKey: ProductKey.LLM_CLUSTERS,
        productName: 'Clusters',
        icon: <IconScatter />,
        accentColor: 'var(--color-product-llm-clusters-light)',
        accentColorDark: 'var(--color-product-llm-analytics-dark)',
        hedgehog: HedgehogScientist,
        text: {
            'needs-setup': {
                headline: 'Find the patterns in how people use your AI',
                lead: 'Clusters group similar traces, generations, and evaluation results, so you can see what people actually ask for, where conversations go wrong, and which failures repeat. Clustering runs on your AI observability data, so it starts with sending events.',
                hint: 'Point the setup agent at your project root. Setup costs are on us, no API key needed:',
            },
            'waiting-for-data': {
                headline: 'AI events are flowing. Waiting for the first clustering run',
                lead: 'Clustering runs on a schedule and needs enough data to work with: around 1,000 traces or generations in the past week. Once your project reaches that, the first clusters appear after the next run. You can skip ahead to manage clustering jobs in the meantime.',
            },
        },
        // Once AI events flow there is nothing left to install: the wait is on the scheduled run.
        wizard: { 'needs-setup': { slug: 'ai-observability', pinProjectId: true } },
        docsUrl: 'https://posthog.com/docs/ai-observability/clusters',
        manualSetupUrl: 'https://posthog.com/docs/ai-observability/installation',
        previewLabel: 'Clusters, once your traces are grouped',
        Preview: ClustersPreview,
    },
}
