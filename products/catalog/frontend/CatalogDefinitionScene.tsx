import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonSkeleton,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import type { CatalogNodeDTOApi } from 'products/catalog/frontend/generated/api.schemas'

import { STATUS_COLOR, STATUS_LABEL } from './catalogConstants'
import { CatalogDefinitionColumnsTable } from './CatalogDefinitionColumnsTable'
import { CatalogDefinitionSceneLogicProps, catalogDefinitionSceneLogic } from './catalogDefinitionSceneLogic'

type DefinitionTab = 'overview' | 'lineage' | 'usage' | 'history' | 'discuss'

export const scene: SceneExport<CatalogDefinitionSceneLogicProps> = {
    component: CatalogDefinitionScene,
    logic: catalogDefinitionSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id || '' }),
    productKey: ProductKey.CATALOG,
}

export function CatalogDefinitionScene({ id }: CatalogDefinitionSceneLogicProps): JSX.Element {
    return (
        <BindLogic logic={catalogDefinitionSceneLogic} props={{ id }}>
            <CatalogDefinitionSceneContent />
        </BindLogic>
    )
}

function CatalogDefinitionSceneContent(): JSX.Element {
    const { definition, definitionLoading } = useValues(catalogDefinitionSceneLogic)
    const [activeTab, setActiveTab] = useState<DefinitionTab>('overview')

    if (definitionLoading && !definition) {
        return (
            <SceneContent>
                <LemonSkeleton className="h-8 w-64" />
                <LemonSkeleton className="h-4 w-96" />
            </SceneContent>
        )
    }

    if (!definition) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name="Definition not found"
                    description="The catalog definition you're looking for doesn't exist or has been deleted."
                    resourceType={{ type: 'data_warehouse' }}
                />
            </SceneContent>
        )
    }

    const tabs: LemonTab<DefinitionTab>[] = [
        {
            key: 'overview',
            label: 'Overview',
            content: <OverviewTab definition={definition} />,
        },
        {
            key: 'lineage',
            label: 'Lineage',
            tooltip: 'Coming soon',
            content: <ComingSoonTab label="Lineage" />,
        },
        {
            key: 'usage',
            label: 'Usage',
            tooltip: 'Coming soon',
            content: <ComingSoonTab label="Usage" />,
        },
        {
            key: 'history',
            label: 'History',
            tooltip: 'Coming soon',
            content: <ComingSoonTab label="History" />,
        },
        {
            key: 'discuss',
            label: 'Discuss',
            tooltip: 'Coming soon',
            content: <ComingSoonTab label="Discuss" />,
        },
    ]

    return (
        <SceneContent>
            <DefinitionHeader definition={definition} />
            <LemonTabs activeKey={activeTab} onChange={setActiveTab} tabs={tabs} />
        </SceneContent>
    )
}

function DefinitionHeader({ definition }: { definition: CatalogNodeDTOApi }): JSX.Element {
    const { pendingEdits, isDirty } = useValues(catalogDefinitionSceneLogic)
    const { setEdits, clearEdits, saveDefinition } = useActions(catalogDefinitionSceneLogic)

    const name = pendingEdits.name ?? definition.name
    const tags = pendingEdits.tags ?? definition.tags ?? []

    return (
        <div className="flex flex-col gap-3">
            <SceneTitleSection
                name={name}
                description={`${definition.kind} · ${definition.columns.length} column${
                    definition.columns.length === 1 ? '' : 's'
                }`}
                resourceType={{ type: 'data_warehouse' }}
                actions={
                    <LemonTag type={STATUS_COLOR[definition.status] ?? 'default'}>
                        {STATUS_LABEL[definition.status] ?? definition.status}
                    </LemonTag>
                }
            />
            <div className="flex items-center gap-2">
                <span className="text-sm text-secondary w-24 shrink-0">Tags</span>
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={tags}
                    options={tags.map((t) => ({ key: t, label: t }))}
                    onChange={(next) => setEdits({ tags: next })}
                    placeholder="Add a tag and press enter"
                />
            </div>
            {isDirty && (
                <div className="flex justify-end gap-2">
                    <LemonButton type="tertiary" onClick={clearEdits}>
                        Discard
                    </LemonButton>
                    <LemonButton type="primary" onClick={saveDefinition}>
                        Save definition
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

function OverviewTab({ definition }: { definition: CatalogNodeDTOApi }): JSX.Element {
    const { pendingEdits } = useValues(catalogDefinitionSceneLogic)
    const { setEdits } = useActions(catalogDefinitionSceneLogic)

    const description = pendingEdits.synthetic_description ?? definition.description ?? ''
    const semanticRole = pendingEdits.semantic_role ?? definition.semantic_role ?? ''
    const businessDomain = pendingEdits.business_domain ?? definition.business_domain ?? ''

    return (
        <div className="flex flex-col gap-6">
            <Field
                label="Description"
                hint="What this table contains, when to use it, and caveats. Markdown supported."
            >
                <LemonTextArea
                    value={description}
                    onChange={(next) => setEdits({ synthetic_description: next })}
                    placeholder="Describe what's in this table"
                    minRows={4}
                />
            </Field>
            <div className="grid grid-cols-2 gap-4">
                <Field label="Semantic role" hint="fact · dimension · bridge · event_source · identity">
                    <LemonInput
                        value={semanticRole}
                        onChange={(next) => setEdits({ semantic_role: next })}
                        placeholder="e.g. fact"
                    />
                </Field>
                <Field label="Business domain" hint="billing · crm · product_usage · support">
                    <LemonInput
                        value={businessDomain}
                        onChange={(next) => setEdits({ business_domain: next })}
                        placeholder="e.g. billing"
                    />
                </Field>
            </div>
            <Field
                label="Columns"
                hint="Edit a column's semantic type, PII class, or description inline. Save per row."
            >
                <CatalogDefinitionColumnsTable />
            </Field>
        </div>
    )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-baseline gap-2">
                <span className="text-sm font-medium">{label}</span>
                {hint && <span className="text-xs text-secondary">{hint}</span>}
            </div>
            {children}
        </div>
    )
}

function ComingSoonTab({ label }: { label: string }): JSX.Element {
    return <LemonBanner type="info">{label} view is coming soon.</LemonBanner>
}
