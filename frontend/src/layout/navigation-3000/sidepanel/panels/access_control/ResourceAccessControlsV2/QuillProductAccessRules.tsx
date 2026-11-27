import type { CellContext } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { createContext, useContext } from 'react'

import { Button, DataTable } from '@posthog/quill'

import { APIScopeObject, AccessControlLevel } from '~/types'

import { accessControlsLogic } from './accessControlsLogic'
import type { AccessDetailSubjectScope } from './accessDetailLogic'
import { getEntryId, inheritedFor, productLevelOptions } from './helpers'
import { QuillAccessDetailSection } from './QuillAccessDetailSection'
import { QuillLevelSelect } from './QuillLevelSelect'
import { type ProductRow, productAccessColumns } from './QuillProductNameCell'
import type { AccessControlSettingsEntry } from './types'

interface ProductRowEditing {
    entry: AccessControlSettingsEntry
    availableLevels: AccessControlLevel[]
    cannotEditReason: string | undefined
    onSetLevel: (resource: APIScopeObject, level: AccessControlLevel | null) => void
}

// DataTable renders each cell function as a component, so the cells live at module scope and read the edit state
// from context. Rebuilding them when a save starts would remount the access select and drop keyboard focus.
const ProductRowEditingContext = createContext<ProductRowEditing | null>(null)

function useProductRowEditing(): ProductRowEditing {
    const rowEditing = useContext(ProductRowEditingContext)
    if (!rowEditing) {
        throw new Error('Product access cells must render inside ProductRowEditingContext')
    }
    return rowEditing
}

function AccessCell({ row }: CellContext<ProductRow, unknown>): JSX.Element {
    const { entry, availableLevels, cannotEditReason, onSetLevel } = useProductRowEditing()
    const resource = entry.resources[row.original.key]

    return (
        <QuillLevelSelect
            aria-label={`${row.original.label} access`}
            value={resource?.access_level ?? null}
            options={productLevelOptions(availableLevels, resource, row.original.label)}
            onChange={(level) => onSetLevel(row.original.key, level)}
            disabledReason={cannotEditReason}
            inherited={inheritedFor(resource, row.original.label.toLowerCase())}
            allowNoOverride
            className="w-56"
        />
    )
}

const COLUMNS = productAccessColumns(AccessCell)

export function QuillProductAccessRules({
    projectId,
    scopeType,
    entry,
    subjectNoun,
    cannotEditReason,
}: {
    projectId: string
    scopeType: AccessDetailSubjectScope
    entry: AccessControlSettingsEntry
    subjectNoun: string
    cannotEditReason: string | undefined
}): JSX.Element {
    const { availableResourceLevels, showAllProducts, productsCollapse } = useValues(accessControlsLogic({ projectId }))
    const { setSubjectResourceAccess, setShowAllProducts } = useActions(accessControlsLogic({ projectId }))

    const subjectId = getEntryId(entry)
    const { visibleResources, collapsedCount, canCollapse } = productsCollapse

    const rowEditing: ProductRowEditing = {
        entry,
        availableLevels: availableResourceLevels,
        cannotEditReason,
        onSetLevel: (resource, level) => setSubjectResourceAccess(scopeType, subjectId, resource, level),
    }

    return (
        <QuillAccessDetailSection title="Products" description={`The access this ${subjectNoun} has to each product.`}>
            <ProductRowEditingContext.Provider value={rowEditing}>
                <DataTable
                    className="rounded-md border border-border"
                    columns={COLUMNS}
                    data={visibleResources}
                    getRowId={(row) => row.key}
                    fullWidth
                />
            </ProductRowEditingContext.Provider>
            {canCollapse && (
                <div className="flex">
                    <Button
                        variant="link"
                        size="inline"
                        onClick={() => setShowAllProducts(!showAllProducts)}
                        data-attr="access-detail-toggle-products"
                    >
                        {showAllProducts ? 'Show fewer' : `Show ${collapsedCount} more products with no overrides`}
                    </Button>
                </div>
            )}
        </QuillAccessDetailSection>
    )
}
