import * as scientistPng from '@posthog/brand/hoggies/png/scientist'
import { IconScatter } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { ClustersEnableButton } from '../clusters/ClustersEnableButton'
import { ClustersPreview } from './ClustersPreview'
import { clustersSetupLogic } from './clustersSetupLogic'
import { ClustersWaitingState } from './ClustersWaitingState'

const HedgehogScientist = pngHoggie(scientistPng)

export const clustersEmptyState: SceneProductEmptyState = {
    statusLogic: clustersSetupLogic,
    WaitingState: ClustersWaitingState,
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
                headline: 'Waiting for the first clustering run',
                lead: 'Keep sending traces, generations, or evaluations. You can review which data your jobs include while you wait.',
            },
        },
        PrimaryAction: ClustersEnableButton,
        docsUrl: 'https://posthog.com/docs/ai-observability/clusters',
        manualSetupUrl: 'https://posthog.com/docs/ai-observability/installation',
        previewLabel: 'Clusters, once your traces are grouped',
        Preview: ClustersPreview,
    },
}
