import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'
import { AI_OBSERVABILITY_CLUSTER_URL_PATTERN } from './frontend/clusters/constants'

export const manifest: ProductManifest = {
    name: 'AI observability',
    scenes: {
        AIObservability: {
            import: () => import('./frontend/AIObservabilityScene'),
            projectBased: true,
            name: 'AI observability',
            layout: 'app-container',
            description: 'Analyze and understand your AI usage and performance.',
            iconType: 'llm_analytics',
        },
        AIObservabilityTrace: {
            import: () => import('./frontend/AIObservabilityTraceScene'),
            projectBased: true,
            name: 'AI observability trace',
            layout: 'app-container',
        },
        AIObservabilitySession: {
            import: () => import('./frontend/AIObservabilitySessionScene'),
            projectBased: true,
            name: 'AI observability session',
            layout: 'app-container',
        },
        AIObservabilityUsers: {
            import: () => import('./frontend/AIObservabilityUsers'),
            projectBased: true,
            name: 'AI observability users',
            layout: 'app-container',
        },
        AIObservabilityPlayground: {
            import: () => import('./frontend/playground/AIObservabilityPlaygroundScene'),
            projectBased: true,
            name: 'Playground',
            description: 'Test and experiment with LLM prompts in a sandbox environment.',
            layout: 'app-full-scene-height',
            iconType: 'llm_playground',
        },
        AIObservabilityDatasets: {
            import: () => import('./frontend/datasets/AIObservabilityDatasetsScene'),
            projectBased: true,
            name: 'Datasets',
            description: 'Manage datasets for testing and evaluation.',
            layout: 'app-container',
            iconType: 'llm_datasets',
        },
        AIObservabilityDataset: {
            import: () => import('./frontend/datasets/AIObservabilityDatasetScene'),
            projectBased: true,
            name: 'Dataset',
            layout: 'app-container',
            iconType: 'llm_datasets',
        },
        AIObservabilityEvaluations: {
            import: () => import('./frontend/evaluations/AIObservabilityEvaluationsScene'),
            projectBased: true,
            name: 'Evaluations',
            description: 'Configure and monitor automated LLM output evaluations.',
            activityScope: 'AIObservability',
            layout: 'app-container',
            iconType: 'llm_evaluations',
        },
        AIObservabilityEvaluation: {
            import: () => import('./frontend/evaluations/AIObservabilityEvaluation'),
            projectBased: true,
            name: 'Evaluation',
            activityScope: 'AIObservability',
            layout: 'app-container',
            iconType: 'llm_evaluations',
        },
        AIObservabilityEvaluationTemplates: {
            import: () => import('./frontend/evaluations/EvaluationTemplates'),
            projectBased: true,
            name: 'Evaluation templates',
            activityScope: 'AIObservability',
            layout: 'app-container',
            iconType: 'llm_evaluations',
        },
        AIObservabilityTags: {
            import: () => import('./frontend/tags/AIObservabilityTagsScene'),
            projectBased: true,
            name: 'Taggers',
            description: 'Add custom tags to your AI generations automatically.',
            activityScope: 'AIObservability',
            layout: 'app-container',
            iconType: 'llm_tags',
        },
        AIObservabilityTag: {
            import: () => import('./frontend/tags/AIObservabilityTag'),
            projectBased: true,
            name: 'Tagger',
            activityScope: 'AIObservability',
            layout: 'app-container',
            iconType: 'llm_tags',
        },
        AIObservabilityPrompts: {
            import: () => import('./frontend/prompts/LLMPromptsScene'),
            projectBased: true,
            name: 'Prompts',
            description: 'Track and manage your LLM prompts.',
            layout: 'app-container',
            iconType: 'llm_prompts',
        },
        AIObservabilityPrompt: {
            import: () => import('./frontend/prompts/LLMPromptScene'),
            projectBased: true,
            name: 'Prompt',
            layout: 'app-container',
            iconType: 'llm_prompts',
        },
        AIObservabilityClusters: {
            import: () => import('./frontend/clusters/AIObservabilityClustersScene'),
            projectBased: true,
            name: 'Clusters',
            description: 'Discover patterns and clusters in your AI usage.',
            layout: 'app-container',
            iconType: 'llm_clusters',
        },
        AIObservabilityCluster: {
            import: () => import('./frontend/clusters/AIObservabilityClusterScene'),
            projectBased: true,
            name: 'AI observability cluster',
            layout: 'app-container',
            iconType: 'llm_clusters',
        },
    },
    routes: {
        '/ai-observability/dashboard': ['AIObservability', 'aiObservabilityDashboard'],
        '/ai-observability/generations': ['AIObservability', 'aiObservabilityGenerations'],
        '/ai-observability/reviews': ['AIObservability', 'aiObservabilityReviews'],
        '/ai-observability/traces': ['AIObservability', 'aiObservabilityTraces'],
        '/ai-observability/traces/:id': ['AIObservabilityTrace', 'aiObservability'],
        '/ai-observability/users': ['AIObservability', 'aiObservabilityUsers'],
        '/ai-observability/errors': ['AIObservability', 'aiObservabilityErrors'],
        '/ai-observability/tools': ['AIObservability', 'aiObservabilityTools'],
        '/ai-observability/sentiment': ['AIObservability', 'aiObservabilitySentiment'],
        '/ai-observability/sessions': ['AIObservability', 'aiObservabilitySessions'],
        '/ai-observability/sessions/:id': ['AIObservability', 'aiObservabilitySessions'],
        '/ai-observability/playground': ['AIObservabilityPlayground', 'aiObservabilityPlayground'],
        '/ai-observability/clusters': ['AIObservabilityClusters', 'aiObservabilityClusters'],
        '/ai-observability/clusters/:runId': ['AIObservabilityClusters', 'aiObservabilityClusters'],
        [AI_OBSERVABILITY_CLUSTER_URL_PATTERN]: ['AIObservabilityCluster', 'aiObservabilityCluster'],
        '/ai-evals/datasets': ['AIObservabilityDatasets', 'aiObservabilityDatasets'],
        '/ai-evals/datasets/:id': ['AIObservabilityDataset', 'aiObservabilityDataset'],
        '/ai-evals/taggers': ['AIObservabilityTags', 'aiObservabilityTags'],
        '/ai-evals/taggers/:id': ['AIObservabilityTag', 'aiObservabilityTag'],
        '/ai-evals/evaluations': ['AIObservabilityEvaluations', 'aiObservabilityEvaluations'],
        '/ai-evals/evaluations/offline/experiments': [
            'AIObservabilityEvaluations',
            'aiObservabilityOfflineEvaluations',
        ],
        '/ai-evals/evaluations/offline/experiments/:experimentId': [
            'AIObservabilityEvaluations',
            'aiObservabilityOfflineEvaluationExperiment',
        ],
        '/ai-evals/evaluations/templates': ['AIObservabilityEvaluationTemplates', 'aiObservabilityEvaluationTemplates'],
        '/ai-evals/evaluations/:id': ['AIObservabilityEvaluation', 'aiObservabilityEvaluation'],
        '/prompt-management/prompts': ['AIObservabilityPrompts', 'aiObservabilityPrompts'],
        '/prompt-management/prompts/:name': ['AIObservabilityPrompt', 'aiObservabilityPrompt'],
    },
    redirects: {
        '/ai-observability': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityDashboard(), searchParams, hashParams).url,
        '/ai-observability/settings': (_params, searchParams, hashParams) => {
            const nextHashParams = { ...hashParams }

            if (Object.prototype.hasOwnProperty.call(nextHashParams, 'llm-analytics-byok')) {
                delete nextHashParams['llm-analytics-byok']
            }
            if (nextHashParams.setting === 'llm-analytics-byok') {
                nextHashParams.setting = 'ai-observability-byok'
            }
            if (nextHashParams.selectedSetting === 'llm-analytics-byok') {
                nextHashParams.selectedSetting = 'ai-observability-byok'
            }
            nextHashParams['ai-observability-byok'] = null

            return combineUrl(urls.settings('project-ai-observability'), searchParams, nextHashParams).url
        },
        '/ai-evals': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityEvaluations(), searchParams, hashParams).url,
        '/ai-evals/evaluations/offline': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityOfflineEvaluations(), searchParams, hashParams).url,
        '/ai-evals/tags': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityTags(), searchParams, hashParams).url,
        '/ai-evals/tags/:id': (params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityTag(params.id), searchParams, hashParams).url,
        '/prompt-management': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityPrompts(), searchParams, hashParams).url,
        '/llm-analytics': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityDashboard(), searchParams, hashParams).url,
        '/llm-analytics/settings': (_params, searchParams, hashParams) => {
            const nextHashParams = { ...hashParams }

            if (Object.prototype.hasOwnProperty.call(nextHashParams, 'llm-analytics-byok')) {
                delete nextHashParams['llm-analytics-byok']
            }
            if (nextHashParams.setting === 'llm-analytics-byok') {
                nextHashParams.setting = 'ai-observability-byok'
            }
            if (nextHashParams.selectedSetting === 'llm-analytics-byok') {
                nextHashParams.selectedSetting = 'ai-observability-byok'
            }
            nextHashParams['ai-observability-byok'] = null

            return combineUrl(urls.settings('project-ai-observability'), searchParams, nextHashParams).url
        },
        '/llm-analytics/dashboard': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityDashboard(), searchParams, hashParams).url,
        '/llm-analytics/generations': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityGenerations(), searchParams, hashParams).url,
        '/llm-analytics/reviews': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityReviews(), searchParams, hashParams).url,
        '/llm-analytics/traces': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityTraces(), searchParams, hashParams).url,
        '/llm-analytics/traces/:id': (params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityTrace(params.id), searchParams, hashParams).url,
        '/llm-analytics/users': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityUsers(), searchParams, hashParams).url,
        '/llm-analytics/errors': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityErrors(), searchParams, hashParams).url,
        '/llm-analytics/tools': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityTools(), searchParams, hashParams).url,
        '/llm-analytics/sentiment': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilitySentiment(), searchParams, hashParams).url,
        '/llm-analytics/sessions': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilitySessions(), searchParams, hashParams).url,
        '/llm-analytics/sessions/:id': (params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilitySession(params.id), searchParams, hashParams).url,
        '/llm-analytics/playground': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityPlayground(), searchParams, hashParams).url,
        '/llm-analytics/clusters': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityClusters(), searchParams, hashParams).url,
        '/llm-analytics/clusters/:runId': (params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityClusters(params.runId), searchParams, hashParams).url,
        '/llm-analytics/clusters/:runId/:clusterId': (params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityCluster(params.runId, params.clusterId), searchParams, hashParams).url,
        '/llm-analytics/datasets': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityDatasets(), searchParams, hashParams).url,
        '/llm-analytics/datasets/:id': (params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityDataset(params.id), searchParams, hashParams).url,
        '/llm-analytics/tags': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityTags(), searchParams, hashParams).url,
        '/llm-analytics/tags/:id': (params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityTag(params.id), searchParams, hashParams).url,
        '/llm-analytics/evaluations': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityEvaluations(), searchParams, hashParams).url,
        '/llm-analytics/evaluations/offline': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityOfflineEvaluations(), searchParams, hashParams).url,
        '/llm-analytics/evaluations/offline/experiments': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityOfflineEvaluations(), searchParams, hashParams).url,
        '/llm-analytics/evaluations/offline/experiments/:experimentId': (params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityOfflineEvaluationExperiment(params.experimentId), searchParams, hashParams)
                .url,
        '/llm-analytics/evaluations/templates': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityEvaluationTemplates(), searchParams, hashParams).url,
        '/llm-analytics/evaluations/:id': (params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityEvaluation(params.id), searchParams, hashParams).url,
        '/llm-analytics/prompts': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityPrompts(), searchParams, hashParams).url,
        '/llm-analytics/prompts/:name': (params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityPrompt(params.name), searchParams, hashParams).url,
        '/llm-observability': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityDashboard(), searchParams, hashParams).url,
        '/llm-observability/dashboard': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityDashboard(), searchParams, hashParams).url,
        '/llm-observability/generations': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityGenerations(), searchParams, hashParams).url,
        '/llm-observability/reviews': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityReviews(), searchParams, hashParams).url,
        '/llm-observability/traces': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityTraces(), searchParams, hashParams).url,
        '/llm-observability/traces/:id': (params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityTrace(params.id), searchParams, hashParams).url,
        '/llm-observability/users': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityUsers(), searchParams, hashParams).url,
        '/llm-observability/playground': (_params, searchParams, hashParams) =>
            combineUrl(urls.aiObservabilityPlayground(), searchParams, hashParams).url,
    },
    urls: {
        aiObservabilityDashboard: (): string => '/ai-observability/dashboard',
        aiObservabilityGenerations: (): string => '/ai-observability/generations',
        aiObservabilityReviews: (): string => '/ai-observability/reviews',
        aiObservabilityTraces: (): string => '/ai-observability/traces',
        aiObservabilityTrace: (
            id: string,
            params?: {
                event?: string
                timestamp?: string
                exception_ts?: string
                search?: string
                tab?: string
                msg?: string
            }
        ): string => {
            const queryParams = new URLSearchParams(params)
            const stringifiedParams = queryParams.toString()
            return `/ai-observability/traces/${id}${stringifiedParams ? `?${stringifiedParams}` : ''}`
        },
        aiObservabilityUsers: (): string => '/ai-observability/users',
        aiObservabilityErrors: (): string => '/ai-observability/errors',
        aiObservabilityTools: (): string => '/ai-observability/tools',
        aiObservabilitySentiment: (): string => '/ai-observability/sentiment',
        aiObservabilitySessions: (): string => '/ai-observability/sessions',
        aiObservabilitySession: (
            id: string,
            params?: {
                timestamp?: string
            }
        ): string => {
            const queryParams = new URLSearchParams(params)
            const stringifiedParams = queryParams.toString()
            return `/ai-observability/sessions/${id}${stringifiedParams ? `?${stringifiedParams}` : ''}`
        },
        aiObservabilityPlayground: (): string => '/ai-observability/playground',
        aiObservabilityDatasets: (): string => '/ai-evals/datasets',
        aiObservabilityDataset: (id: string, params?: { item?: string }): string =>
            combineUrl(`/ai-evals/datasets/${id}`, params).url,
        aiObservabilityTags: (): string => '/ai-evals/taggers',
        aiObservabilityTag: (id: string): string => `/ai-evals/taggers/${id}`,
        aiObservabilityEvaluations: (): string => '/ai-evals/evaluations',
        aiObservabilityOfflineEvaluations: (): string => '/ai-evals/evaluations/offline/experiments',
        aiObservabilityOfflineEvaluationExperiment: (experimentId: string, encode: boolean = true): string =>
            `/ai-evals/evaluations/offline/experiments/${encode ? encodeURIComponent(experimentId) : experimentId}`,
        aiObservabilityEvaluationTemplates: (): string => '/ai-evals/evaluations/templates',
        aiObservabilityEvaluation: (id: string): string => `/ai-evals/evaluations/${id}`,
        aiObservabilityPrompts: (): string => '/prompt-management/prompts',
        aiObservabilityPrompt: (name: string): string => `/prompt-management/prompts/${name}`,
        aiObservabilityClusters: (runId?: string): string =>
            runId ? `/ai-observability/clusters/${encodeURIComponent(runId)}` : '/ai-observability/clusters',
        aiObservabilityCluster: (runId: string, clusterId: number | string): string =>
            `/ai-observability/clusters/${encodeURIComponent(runId)}/${clusterId}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'LLM analytics',
            displayLabel: 'AI observability',
            intents: [
                ProductKey.AI_OBSERVABILITY,
                ProductKey.LLM_EVALUATIONS,
                ProductKey.LLM_DATASETS,
                ProductKey.LLM_PROMPTS,
                ProductKey.LLM_CLUSTERS,
            ],
            category: ProductItemCategory.AI_ENGINEERING,
            visualOrder: 1,
            type: 'llm_analytics',
            iconType: 'llm_analytics' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-analytics-light)'] as FileSystemIconColor,
            href: urls.aiObservabilityDashboard(),
            sceneKey: 'AIObservability',
        },
        {
            path: 'Playground',
            intents: [ProductKey.AI_OBSERVABILITY],
            category: ProductItemCategory.AI_ENGINEERING,
            type: 'llm_playground',
            iconType: 'llm_playground' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-analytics-light)'] as FileSystemIconColor,
            href: urls.aiObservabilityPlayground(),
            sceneKey: 'AIObservabilityPlayground',
        },
        {
            path: 'Clusters',
            intents: [ProductKey.LLM_CLUSTERS],
            category: ProductItemCategory.AI_ENGINEERING,
            type: 'llm_clusters',
            iconType: 'llm_clusters' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-clusters-light)'] as FileSystemIconColor,
            href: urls.aiObservabilityClusters(),
            sceneKey: 'AIObservabilityClusters',
        },
        {
            path: 'Datasets',
            intents: [ProductKey.LLM_DATASETS],
            category: ProductItemCategory.AI_ENGINEERING,
            type: 'llm_datasets',
            iconType: 'llm_datasets' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-datasets-light)'] as FileSystemIconColor,
            href: urls.aiObservabilityDatasets(),
            flag: FEATURE_FLAGS.LLM_ANALYTICS_DATASETS,
            tags: ['beta'],
            sceneKey: 'AIObservabilityDatasets',
        },
        {
            path: 'Evaluations',
            intents: [ProductKey.LLM_EVALUATIONS],
            category: ProductItemCategory.AI_ENGINEERING,
            type: 'llm_evaluations',
            iconType: 'llm_evaluations' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-evaluations-light)'] as FileSystemIconColor,
            href: urls.aiObservabilityEvaluations(),
            sceneKey: 'AIObservabilityEvaluations',
        },
        {
            path: 'Taggers',
            intents: [ProductKey.AI_OBSERVABILITY],
            category: ProductItemCategory.AI_ENGINEERING,
            type: 'llm_tags',
            iconType: 'llm_tags' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-analytics-light)'] as FileSystemIconColor,
            href: urls.aiObservabilityTags(),
            flag: FEATURE_FLAGS.LLM_ANALYTICS_TAGS,
            tags: ['alpha'],
            sceneKey: 'AIObservabilityTags',
        },
        {
            path: 'Prompts',
            intents: [ProductKey.LLM_PROMPTS],
            category: ProductItemCategory.AI_ENGINEERING,
            type: 'llm_prompts',
            iconType: 'llm_prompts' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-prompts-light)'] as FileSystemIconColor,
            href: urls.aiObservabilityPrompts(),
            tags: ['beta'],
            sceneKey: 'AIObservabilityPrompts',
        },
    ],
}
