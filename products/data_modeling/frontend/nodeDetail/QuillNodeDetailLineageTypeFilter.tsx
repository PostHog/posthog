import { useActions, useValues } from 'kea'

import {
    DropdownMenu,
    DropdownMenuContent,
    FilterCheckboxSubMenu,
    FilterClearItem,
    FilterMenuTrigger,
} from '@posthog/quill'

import { DataModelingNodeType } from '~/types'

import { LINEAGE_FILTER_TYPES } from '../lineage/modelsLineageLogic'
import { NODE_TYPE_TAG_SETTINGS } from '../lineage/nodeStyles'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

const TYPE_OPTIONS = LINEAGE_FILTER_TYPES.map((type) => ({ value: type, label: NODE_TYPE_TAG_SETTINGS[type].label }))

export function QuillNodeDetailLineageTypeFilter({ id }: { id: string }): JSX.Element {
    const { lineageTypeFilter } = useValues(nodeDetailSceneLogic({ id }))
    const { setLineageTypeFilter } = useActions(nodeDetailSceneLogic({ id }))
    const filtered = lineageTypeFilter.length !== LINEAGE_FILTER_TYPES.length

    return (
        <DropdownMenu>
            <FilterMenuTrigger active={filtered} dataAttr="node-detail-lineage-type-filter" />
            <DropdownMenuContent align="start">
                <FilterCheckboxSubMenu<DataModelingNodeType>
                    label="Type"
                    allLabel="All types"
                    pluralNoun="types"
                    options={TYPE_OPTIONS}
                    selected={filtered ? lineageTypeFilter : []}
                    onChange={(selected) => setLineageTypeFilter(selected.length ? selected : LINEAGE_FILTER_TYPES)}
                    optionDataAttr="node-detail-lineage-type-filter-option"
                />
                <FilterClearItem
                    active={filtered}
                    onClear={() => setLineageTypeFilter(LINEAGE_FILTER_TYPES)}
                    dataAttr="node-detail-lineage-reset-filters"
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
