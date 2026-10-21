import { useActions, useValues } from 'kea'
import { Fragment, ReactNode, useMemo, useRef } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { CustomFacetsProduct, customFacetsLogic } from './customFacetsLogic'
import { FacetGroupItem, facetsByGroup, filterFacetsByName } from './facetGroups'

const DEFAULT_WIDTH_PX = 240
const COLLAPSE_THRESHOLD_PX = 120

interface AddFacetGroupTypes {
    attribute: TaxonomicFilterGroupType
    resourceAttribute: TaxonomicFilterGroupType
}

export interface FacetRailProps<T extends FacetGroupItem> {
    /** Omit, with `addFacetGroupTypes`, for a product without custom facets: the rail then hides the add button. */
    product?: CustomFacetsProduct
    facets: T[]
    /** Renders one facet. A facet that the name search hides still renders, so its logic stays mounted. */
    renderFacet: (facet: T, hidden: boolean) => JSX.Element
    facetNameSearch: string
    onFacetNameSearchChange: (value: string) => void
    onCollapsedChange: (collapsed: boolean) => void
    addFacetGroupTypes?: AddFacetGroupTypes
    /** Persisted width keys. Frozen: a change resets every user's saved rail width. */
    resizerLogicKey: string
    resizerPersistPrefix: string
    /** Prefix for the rail's data-attrs, e.g. `logs-facet-rail`. Frozen: autocapture and tests select on them. */
    dataAttrPrefix: string
    /** Shown above the facets, such as an error when the facet list itself failed to load. */
    notice?: ReactNode
}

/** Resizable left-hand facet rail: a facet-name search, an add-custom-facet button, and the grouped facets. */
export function FacetRail<T extends FacetGroupItem>({
    product,
    facets,
    renderFacet,
    facetNameSearch,
    onFacetNameSearchChange,
    onCollapsedChange,
    addFacetGroupTypes,
    resizerLogicKey,
    resizerPersistPrefix,
    dataAttrPrefix,
    notice,
}: FacetRailProps<T>): JSX.Element {
    const railRef = useRef<HTMLDivElement>(null)

    const resizerLogicProps: ResizerLogicProps = useMemo(
        () => ({
            logicKey: resizerLogicKey,
            containerRef: railRef,
            persistent: true,
            persistPrefix: resizerPersistPrefix,
            placement: 'right',
            closeThreshold: COLLAPSE_THRESHOLD_PX,
            onToggleClosed: onCollapsedChange,
        }),
        [resizerLogicKey, resizerPersistPrefix, onCollapsedChange]
    )
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    // Every visible facet renders a container, whether or not the field-name search matches it: a
    // non-matching one renders nothing but stays mounted, so clearing the search doesn't refetch.
    const matchingKeys = new Set(filterFacetsByName(facets, facetNameSearch).map((f) => f.key))
    const groups = facetsByGroup(facets)

    return (
        <div
            ref={railRef}
            // In a narrow host the rail stacks above the results, so the full width replaces the dragged width.
            className="relative flex flex-col shrink-0 border rounded bg-surface-primary overflow-hidden @max-[48rem]/facet-rail-host:!w-full @max-[48rem]/facet-rail-host:!max-w-full @max-[48rem]/facet-rail-host:max-h-48"
            // The width is the user's alone: a fixed min (not min-content) so a long facet value
            // can never force the rail wider — values truncate to fit instead.
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: desiredSize ?? DEFAULT_WIDTH_PX, minWidth: COLLAPSE_THRESHOLD_PX, maxWidth: '40%' }}
            data-attr={dataAttrPrefix}
        >
            <div className="flex items-center gap-1 px-2 py-1 border-b">
                <LemonInput
                    type="search"
                    size="small"
                    fullWidth
                    placeholder="Search facets…"
                    value={facetNameSearch}
                    onChange={onFacetNameSearchChange}
                    data-attr={`${dataAttrPrefix}-search`}
                />
                {product && addFacetGroupTypes && (
                    <AddCustomFacetButton
                        product={product}
                        groupTypes={addFacetGroupTypes}
                        dataAttrPrefix={dataAttrPrefix}
                    />
                )}
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto p-2">
                {notice}
                {matchingKeys.size === 0 && facetNameSearch.trim() && (
                    <div className="px-1 text-xs text-muted">No matching facets</div>
                )}
                {groups.map(([group, groupFacets]) => (
                    <div key={group}>
                        {groupFacets.some((facet) => matchingKeys.has(facet.key)) && (
                            <div className="px-1 pb-1 mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted border-b border-primary">
                                {group}
                            </div>
                        )}
                        {groupFacets.map((facet) => (
                            <Fragment key={facet.key}>{renderFacet(facet, !matchingKeys.has(facet.key))}</Fragment>
                        ))}
                    </div>
                ))}
            </div>
            <Resizer
                {...resizerLogicProps}
                visible={false}
                offset="0.25rem"
                className="@max-[48rem]/facet-rail-host:hidden"
                handleClassName="rounded my-1"
            />
        </div>
    )
}

function AddCustomFacetButton({
    product,
    groupTypes,
    dataAttrPrefix,
}: {
    product: CustomFacetsProduct
    groupTypes: AddFacetGroupTypes
    dataAttrPrefix: string
}): JSX.Element | null {
    const { addCustomFacet } = useActions(customFacetsLogic({ product }))
    const { customFacetsEnabled, entriesLoading } = useValues(customFacetsLogic({ product }))
    if (!customFacetsEnabled) {
        return null
    }
    return (
        <TaxonomicStringPopover
            groupType={groupTypes.attribute}
            groupTypes={[groupTypes.attribute, groupTypes.resourceAttribute]}
            placeholder={null}
            size="small"
            icon={<IconPlus />}
            tooltip="Add custom facet"
            disabledReason={entriesLoading ? 'Custom facets are updating' : undefined}
            data-attr={`${dataAttrPrefix}-add`}
            onChange={(value, groupType) =>
                addCustomFacet(value, groupType === groupTypes.resourceAttribute ? 'resourceAttribute' : 'attribute')
            }
        />
    )
}
