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

interface SelectionState {
    label: string
    group: TaxonomicFilterGroupType
    value: TaxonomicFilterValue | null
    name?: string
}

export function TaxonomicFilterPreview(): JSX.Element {
    const [legacy, setLegacy] = useState<SelectionState | null>(null)
    const [headless, setHeadless] = useState<SelectionState | null>(null)

    const handle =
        (label: 'legacy' | 'headless') =>
        (group: TaxonomicFilterGroup, value: TaxonomicFilterValue | null, item: any): void => {
            const state: SelectionState = {
                label,
                group: group.type,
                value,
                name: item?.name,
            }
            if (label === 'legacy') {
                setLegacy(state)
            } else {
                setHeadless(state)
            }
        }

    return (
        <div className="border border-dashed border-warning-light rounded p-3 bg-surface-primary">
            <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-semibold m-0">Taxonomic Filter — parity preview</h3>
                <span className="text-xs text-secondary">
                    Disposable. Compare legacy (left) vs headless (right). Both share the same input props.
                </span>
            </div>
            <div className="grid grid-cols-2 gap-3">
                <div className="border rounded p-2 min-h-72">
                    <div className="text-xs text-secondary mb-1">Legacy (kea via flag)</div>
                    <TaxonomicFilter
                        taxonomicFilterLogicKey="preview-legacy"
                        taxonomicGroupTypes={PREVIEW_GROUP_TYPES}
                        onChange={handle('legacy')}
                        width={420}
                        height={420}
                    />
                    {legacy && (
                        <div className="mt-2 text-xs">
                            <code>{legacy.group}</code> / <code>{String(legacy.value)}</code>
                            {legacy.name ? ` (${legacy.name})` : ''}
                        </div>
                    )}
                </div>

                <div className="border rounded p-2 min-h-72">
                    <div className="text-xs text-secondary mb-1">Headless (TaxonomicFilterAdapter)</div>
                    <TaxonomicFilterAdapter
                        taxonomicGroupTypes={PREVIEW_GROUP_TYPES}
                        onChange={handle('headless')}
                        width={420}
                        height={420}
                    />
                    {headless && (
                        <div className="mt-2 text-xs">
                            <code>{headless.group}</code> / <code>{String(headless.value)}</code>
                            {headless.name ? ` (${headless.name})` : ''}
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
