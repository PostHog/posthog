import { IconChevronDown, IconDatabase } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown } from '@posthog/lemon-ui'

import { DataModelingNodeType } from '~/types'

import { LINEAGE_FILTER_TYPES } from './modelsLineageLogic'
import { NODE_TYPE_TAG_SETTINGS } from './nodeStyles'

export interface LineageTypeFilterProps {
    value: DataModelingNodeType[]
    onChange: (value: DataModelingNodeType[]) => void
    dataAttr: string
}

function summarize(selected: DataModelingNodeType[]): string {
    if (selected.length === LINEAGE_FILTER_TYPES.length) {
        return 'All types'
    }
    if (selected.length === 0) {
        return 'No types'
    }
    if (selected.length === 1) {
        return NODE_TYPE_TAG_SETTINGS[selected[0]].label
    }
    return `${selected.length} types`
}

export function LineageTypeFilter({ value, onChange, dataAttr }: LineageTypeFilterProps): JSX.Element {
    const toggle = (type: DataModelingNodeType): void =>
        onChange(value.includes(type) ? value.filter((selected) => selected !== type) : [...value, type])

    return (
        <LemonDropdown
            closeOnClickInside={false}
            overlay={
                <div className="flex flex-col gap-px p-1">
                    {LINEAGE_FILTER_TYPES.map((type) => (
                        <LemonButton
                            key={type}
                            type="tertiary"
                            size="small"
                            fullWidth
                            icon={<LemonCheckbox checked={value.includes(type)} className="pointer-events-none" />}
                            sideIcon={<IconDatabase style={{ color: NODE_TYPE_TAG_SETTINGS[type].color }} />}
                            onClick={() => toggle(type)}
                        >
                            {NODE_TYPE_TAG_SETTINGS[type].label}
                        </LemonButton>
                    ))}
                </div>
            }
        >
            <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />} data-attr={dataAttr}>
                {summarize(value)}
            </LemonButton>
        </LemonDropdown>
    )
}
