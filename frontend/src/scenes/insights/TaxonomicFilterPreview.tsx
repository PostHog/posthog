/**
 * Side-by-side preview of the legacy kea-driven TaxonomicFilter and the new
 * headless implementation for visual / behavioural comparison while parity is
 * being validated.
 *
 * Mounted at the top of InsightAsScene when `isEditing` is true. Disposable —
 * delete this whole file once we flip the flag and the new path is the
 * default. Tracking removal in TAXONOMIC_FILTER_REWRITE_PRD.md (Phase 6).
 */
import { useState } from 'react'

import { TaxonomicFilterHeadless } from 'lib/components/TaxonomicFilter/headless'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterAdapter } from 'lib/components/TaxonomicFilter/TaxonomicFilterAdapter'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'

const PREVIEW_GROUP_TYPES: TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.Events,
    TaxonomicFilterGroupType.Actions,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.Cohorts,
]

type Variant = 'legacy' | 'headless' | 'autocomplete'

interface SelectionState {
    variant: Variant
    group: TaxonomicFilterGroupType
    value: TaxonomicFilterValue | null
    name?: string
}

export function TaxonomicFilterPreview(): JSX.Element {
    const [legacy, setLegacy] = useState<SelectionState | null>(null)
    const [headless, setHeadless] = useState<SelectionState | null>(null)
    const [autocomplete, setAutocomplete] = useState<SelectionState | null>(null)

    const handle =
        (variant: Variant) =>
        (group: TaxonomicFilterGroup, value: TaxonomicFilterValue | null, item: any): void => {
            const state: SelectionState = { variant, group: group.type, value, name: item?.name }
            if (variant === 'legacy') {
                setLegacy(state)
            } else if (variant === 'headless') {
                setHeadless(state)
            } else {
                setAutocomplete(state)
            }
        }

    return (
        <div className="border border-dashed border-warning-light rounded p-3 bg-surface-primary">
            <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-semibold m-0">Taxonomic Filter — variation preview</h3>
                <span className="text-xs text-secondary">Disposable. Three variants share the same input props.</span>
            </div>
            <div className="grid grid-cols-3 gap-3">
                <div className="border rounded p-2 min-h-72">
                    <div className="text-xs text-secondary mb-1">Legacy (kea via flag)</div>
                    <TaxonomicFilter
                        taxonomicFilterLogicKey="preview-legacy"
                        taxonomicGroupTypes={PREVIEW_GROUP_TYPES}
                        onChange={handle('legacy')}
                        width={400}
                        height={420}
                    />
                    <SelectionEcho state={legacy} />
                </div>

                <div className="border rounded p-2 min-h-72">
                    <div className="text-xs text-secondary mb-1">Headless (Categories + Panel)</div>
                    <TaxonomicFilterAdapter
                        taxonomicGroupTypes={PREVIEW_GROUP_TYPES}
                        onChange={handle('headless')}
                        width={400}
                        height={420}
                    />
                    <SelectionEcho state={headless} />
                </div>

                <div className="border rounded p-2 min-h-72">
                    <div className="text-xs text-secondary mb-1">Headless — base-ui Autocomplete input</div>
                    <TaxonomicFilterHeadless.Root
                        taxonomicGroupTypes={PREVIEW_GROUP_TYPES}
                        onChange={handle('autocomplete')}
                    >
                        <TaxonomicFilterHeadless.AutocompleteInput popupClassName="max-h-80 overflow-auto" />
                        <TaxonomicFilterHeadless.Categories className="flex flex-row flex-wrap gap-1 mt-2" />
                    </TaxonomicFilterHeadless.Root>
                    <SelectionEcho state={autocomplete} />
                </div>
            </div>
        </div>
    )
}

function SelectionEcho({ state }: { state: SelectionState | null }): JSX.Element | null {
    if (!state) {
        return null
    }
    return (
        <div className="mt-2 text-xs">
            <code>{state.group}</code> / <code>{String(state.value)}</code>
            {state.name ? ` (${state.name})` : ''}
        </div>
    )
}
