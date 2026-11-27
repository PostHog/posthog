import type { CellContext, ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { createContext, useContext } from 'react'

import { IconInfo } from '@posthog/icons'
import { Button, DataTable, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { getAccessControlTooltip } from 'lib/utils/accessControlUtils'

import { APIScopeObject, AccessControlLevel } from '~/types'

import { accessControlsLogic } from './accessControlsLogic'
import type { AccessDetailSubjectScope } from './accessDetailLogic'
import { getEntryId, getLevelOptionsForResource, inheritedFor } from './helpers'
import { QuillAccessDetailSection } from './QuillAccessDetailSection'
import { QuillLevelSelect } from './QuillLevelSelect'
import { ScopeIcon } from './ScopeIcon'
import type { AccessControlSettingsEntry } from './types'

type ProductRow = { key: APIScopeObject; label: string }

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

function ProductCell({ row }: CellContext<ProductRow, unknown>): JSX.Element {
    const tooltipText = getAccessControlTooltip(row.original.key)

    return (
        <div className="flex items-center gap-2">
            <span className="flex items-center text-muted-foreground">
                <ScopeIcon scope={row.original.key} />
            </span>
            <Text size="xs" weight="medium" render={<span />}>
                {row.original.label}
            </Text>
            {tooltipText && (
                <Tooltip>
                    <TooltipTrigger render={<span className="flex items-center text-muted-foreground" />}>
                        <IconInfo />
                    </TooltipTrigger>
                    <TooltipContent>{tooltipText}</TooltipContent>
                </Tooltip>
            )}
        </div>
    )
}

function AccessCell({ row }: CellContext<ProductRow, unknown>): JSX.Element {
    const { entry, availableLevels, cannotEditReason, onSetLevel } = useProductRowEditing()
    const resource = entry.resources[row.original.key]

    return (
        <QuillLevelSelect
            aria-label={`${row.original.label} access`}
            value={resource?.access_level ?? null}
            options={getLevelOptionsForResource(availableLevels, {
                minimum: resource?.minimum ?? null,
                maximum: resource?.maximum ?? null,
                inheritedLevel: null,
                inheritedReason: null,
                resourceLabel: row.original.label,
            })}
            onChange={(level) => onSetLevel(row.original.key, level)}
            disabledReason={cannotEditReason}
            inherited={inheritedFor(resource, row.original.label.toLowerCase())}
            allowNoOverride
        />
    )
}

const COLUMNS: ColumnDef<ProductRow>[] = [
    { id: 'label', header: 'Product', meta: { expand: true }, enableSorting: false, cell: ProductCell },
    { id: 'access', header: 'Access', meta: { align: 'right' }, enableSorting: false, cell: AccessCell },
]

/** The subject's access to each product, saved as soon as a level is picked. */
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
    const { updateResourceAccessControls, setShowAllProducts } = useActions(accessControlsLogic({ projectId }))

    const subjectId = getEntryId(entry)
    const { visibleResources, collapsedCount, canCollapse } = productsCollapse

    const rowEditing: ProductRowEditing = {
        entry,
        availableLevels: availableResourceLevels,
        cannotEditReason,
        onSetLevel: (resource, level) =>
            updateResourceAccessControls(
                [
                    {
                        resource,
                        access_level: level,
                        role: scopeType === 'role' ? subjectId : null,
                        organization_member: scopeType === 'member' ? subjectId : null,
                    },
                ],
                scopeType
            ),
    }

    return (
        <QuillAccessDetailSection title="Products" description={`The access this ${subjectNoun} has to each product.`}>
            <ProductRowEditingContext.Provider value={rowEditing}>
                <DataTable columns={COLUMNS} data={visibleResources} getRowId={(row) => row.key} fullWidth />
            </ProductRowEditingContext.Provider>
            {canCollapse && (
                <div className="flex">
                    <Button
                        variant="link"
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
