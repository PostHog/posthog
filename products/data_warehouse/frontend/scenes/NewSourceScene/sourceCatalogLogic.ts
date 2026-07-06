import FuseClass from 'fuse.js'
import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { FeatureFlagKey } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { createFuse } from 'lib/utils/fuseSearch'
import { objectsEqual } from 'lib/utils/objects'
import { getSourceDisplayStatus } from 'scenes/data-pipelines/utils/nonHogFunctionTemplatesLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    SourceConfig,
    dataWarehouseSourceCategories,
} from '~/queries/schema/schema-general'
import { HogFunctionTemplateStatus } from '~/types'

import { availableSourcesLogic } from './availableSourcesLogic'
import type { sourceCatalogLogicType } from './sourceCatalogLogicType'
import { sourceWizardLogic } from './sourceWizardLogic'

// Helps kea-typegen reference the Fuse type without a bad `import { Fuse } from 'fuse.js'`.
export interface Fuse extends FuseClass<CatalogItem> {}

export type SourceCategoryFilter = DataWarehouseSourceCategory | 'all'

export const ALL_SOURCES_CATEGORY = 'all'

// Self-managed (S3/GCS/Azure/R2) connectors don't flow through SourceConfig, so place
// them in a sensible catalog bucket explicitly.
const MANUAL_SOURCE_CATEGORY: DataWarehouseSourceCategory = 'File storage'

// Self-managed connectors carry no SourceConfig keywords, and their labels alone ("S3",
// "Google Cloud Storage") miss the terms users actually search ("amazon", "aws", "gcs").
// Keys match ManualLinkSourceType.
const MANUAL_SOURCE_KEYWORDS: Record<string, string[]> = {
    aws: ['amazon', 'aws', 's3', 'amazon web services', 'amazon s3'],
    'google-cloud': ['gcs', 'gcp', 'google cloud', 'google cloud storage'],
    'cloudflare-r2': ['cloudflare', 'r2', 'object storage'],
    azure: ['azure', 'microsoft azure', 'azure blob', 'blob storage'],
}

// "Request a data warehouse source" survey. We render our own modal and submit the answer
// directly as a `survey sent` event rather than using the posthog-js survey popover.
export const SOURCE_REQUEST_SURVEY_ID = '0190ff15-5032-0000-722a-e13933c140ac'

export interface SourceCatalogLogicProps {
    /** When set, only managed sources whose name is in this list are shown. */
    allowedSources?: ExternalDataSourceType[]
}

export interface CatalogItem {
    /** The source kind passed to the new-source URL (e.g. "Stripe", or "aws" for self-managed). */
    name: string
    label: string
    iconType: string
    iconClassName?: string
    category: DataWarehouseSourceCategory
    keywords: string[]
    status: HogFunctionTemplateStatus
    releaseStatus?: SourceConfig['releaseStatus']
    url: string
    disabledReason?: string | null
    existingSource?: boolean
}

export interface CatalogCategory {
    category: SourceCategoryFilter
    label: string
    count: number
}

export const sourceCatalogLogic = kea<sourceCatalogLogicType>([
    path(['products', 'dataWarehouse', 'sourceCatalogLogic']),
    props({} as SourceCatalogLogicProps),
    connect(() => ({
        values: [
            // Read the managed connector list straight from the /wizard loader rather than
            // sourceWizardLogic.connectors — the latter derives from sourceWizardLogic's
            // `availableSources` prop, which isn't reliably populated when the catalog is
            // mounted outside the wizard (e.g. the pipeline new-source page).
            availableSourcesLogic,
            ['availableSources'],
            sourceWizardLogic,
            ['manualConnectors'],
            featureFlagLogic,
            ['featureFlags'],
            userLogic,
            ['user'],
        ],
    })),
    actions({
        setSearch: (search: string) => ({ search }),
        setSelectedCategory: (category: SourceCategoryFilter) => ({ category }),
        registerInterest: (item: CatalogItem) => ({ item }),
        selectSourceType: (item: CatalogItem) => ({ item }),
        showSourceRequest: true,
        hideSourceRequest: true,
        setSourceRequestText: (text: string) => ({ text }),
        submitSourceRequest: true,
    }),
    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
        selectedCategory: [
            ALL_SOURCES_CATEGORY as SourceCategoryFilter,
            { setSelectedCategory: (_, { category }) => category },
        ],
        sourceRequestModalOpen: [
            false,
            {
                showSourceRequest: () => true,
                hideSourceRequest: () => false,
                submitSourceRequest: () => false,
            },
        ],
        sourceRequestText: [
            '',
            {
                setSourceRequestText: (_, { text }) => text,
                // Reset on open/close, but NOT on submit — the submit listener reads it first.
                showSourceRequest: () => '',
                hideSourceRequest: () => '',
            },
        ],
    }),
    selectors({
        catalogItems: [
            (s) => [
                s.availableSources,
                s.manualConnectors,
                s.featureFlags,
                (_, p: SourceCatalogLogicProps) => p.allowedSources,
            ],
            (availableSources, manualConnectors, featureFlags, allowedSources): CatalogItem[] => {
                const managed = Object.values(availableSources ?? {})
                    .filter((c) => !allowedSources || allowedSources.includes(c.name))
                    .map((connector: SourceConfig): CatalogItem => {
                        // Mirror nonHogFunctionTemplatesLogic: a declared-but-absent flag reads as
                        // off (featureFlagLogic only exposes truthy flags), so flag-gated sources
                        // render as coming-soon ("Notify me") until the user is in the rollout.
                        const featureFlagDefined = !!connector.featureFlag
                        const featureFlagRaw = featureFlags[connector.featureFlag as FeatureFlagKey]
                        const featureFlagValue: boolean | undefined = featureFlagDefined ? !!featureFlagRaw : undefined
                        const { status } = getSourceDisplayStatus(!!connector.unreleasedSource, featureFlagValue)
                        // Only surface alpha/beta while the source is actually connectable.
                        const releaseStatus =
                            status === 'stable' && connector.releaseStatus && connector.releaseStatus !== 'ga'
                                ? connector.releaseStatus
                                : undefined

                        return {
                            name: connector.name,
                            label: connector.label ?? connector.name,
                            iconType: connector.name,
                            iconClassName: connector.iconClassName,
                            category: connector.category ?? MANUAL_SOURCE_CATEGORY,
                            keywords: connector.keywords ?? [],
                            status,
                            releaseStatus,
                            url: urls.dataWarehouseSourceNew(connector.name),
                            disabledReason: connector.disabledReason,
                            existingSource: connector.existingSource,
                        }
                    })

                const selfManaged = manualConnectors.map(
                    (source): CatalogItem => ({
                        name: source.type,
                        label: source.name,
                        iconType: source.type,
                        category: MANUAL_SOURCE_CATEGORY,
                        keywords: MANUAL_SOURCE_KEYWORDS[source.type] ?? [],
                        status: 'stable',
                        url: urls.dataWarehouseSourceNew(source.type),
                    })
                )

                return [...managed, ...selfManaged]
            },
            // featureFlags is a broad dependency that changes identity on every flag refresh;
            // keeping the previous array when the derived catalog is unchanged stops the Fuse
            // index and every tile from re-deriving on unrelated flag updates.
            { resultEqualityCheck: objectsEqual },
        ],

        categoriesWithCounts: [
            (s) => [s.catalogItems],
            (catalogItems): CatalogCategory[] => {
                const counts = new Map<DataWarehouseSourceCategory, number>()
                for (const item of catalogItems) {
                    counts.set(item.category, (counts.get(item.category) ?? 0) + 1)
                }
                const present = dataWarehouseSourceCategories
                    .filter((category) => counts.has(category))
                    .map(
                        (category): CatalogCategory => ({
                            category,
                            label: category,
                            count: counts.get(category) ?? 0,
                        })
                    )
                    // Most-populated categories first; fall back to taxonomy order on a tie.
                    .sort((a, b) => b.count - a.count)
                return [
                    { category: ALL_SOURCES_CATEGORY, label: 'All sources', count: catalogItems.length },
                    ...present,
                ]
            },
        ],

        catalogFuse: [
            (s) => [s.catalogItems],
            (catalogItems): Fuse =>
                createFuse(catalogItems, {
                    keys: ['label', 'name', 'keywords', 'category'],
                }),
        ],

        filteredItems: [
            (s) => [s.catalogItems, s.catalogFuse, s.search, s.selectedCategory],
            (catalogItems, catalogFuse, search, selectedCategory): CatalogItem[] => {
                const trimmed = search.trim()
                const base = trimmed ? catalogFuse.search(trimmed).map((r) => r.item) : catalogItems
                const filtered =
                    selectedCategory === ALL_SOURCES_CATEGORY
                        ? base
                        : base.filter((item) => item.category === selectedCategory)
                // Keep fuzzy-search relevance order when searching; otherwise sort by name.
                return trimmed ? filtered : [...filtered].sort((a, b) => a.label.localeCompare(b.label))
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        registerInterest: ({ item }) => {
            posthog.capture('notify_me_pipeline', {
                name: item.label,
                type: 'source',
                template_id: `managed-${item.name}`,
                email: values.user?.email,
            })
            lemonToast.success('Thank you for your interest! We will notify you when this source is available.')
        },
        selectSourceType: ({ item }) => {
            posthog.capture('selected source type', {
                name: item.label,
                type: item.name,
                category: item.category,
                release_status: item.releaseStatus,
            })
        },
        showSourceRequest: () => {
            posthog.capture('survey shown', { $survey_id: SOURCE_REQUEST_SURVEY_ID })
            // Seed the request with whatever the user just searched, so a "searched for X →
            // no results → request X" flow doesn't make them retype the same term.
            const seed = values.search.trim()
            if (seed) {
                actions.setSourceRequestText(seed)
            }
        },
        submitSourceRequest: () => {
            const response = values.sourceRequestText.trim()
            if (!response) {
                return
            }
            // Submit straight to the survey behind the scenes — no posthog-js survey popover.
            posthog.capture('survey sent', {
                $survey_id: SOURCE_REQUEST_SURVEY_ID,
                $survey_response: response,
            })
            lemonToast.success('Thanks! Your source request has been submitted.')
        },
    })),
])
