import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { LemonSnack, Popover } from '@posthog/lemon-ui'
import { midEllipsis } from 'lib/utils'
import { useState } from 'react'

import { PathCleaningFilter } from '~/types'

import { PathRegexPopover } from './PathRegexPopover'

interface PathCleanFilterItem {
    filter: PathCleaningFilter
    onChange: (filter: PathCleaningFilter) => void
    onRemove: () => void
}

export function PathCleanFilterItem({ filter, onChange, onRemove }: PathCleanFilterItem): JSX.Element {
    const [visible, setVisible] = useState(false)
    const { attributes, listeners, setNodeRef, transform, transition } = useSortable({
        id: String(filter.alias),
    })

    const label = `${filter.alias}::${filter.regex}`

    return (
        <Popover
            visible={visible}
            onClickOutside={() => setVisible(false)}
            overlay={
                <PathRegexPopover
                    filter={filter}
                    onSave={(filter: PathCleaningFilter) => {
                        onChange(filter)
                        setVisible(false)
                    }}
                    onCancel={() => setVisible(false)}
                />
            }
        >
            {/* required for popover placement */}
            <div
                className="relative"
                ref={setNodeRef}
                {...attributes}
                {...listeners}
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    transform: CSS.Translate.toString(transform),
                    transition,
                }}
            >
                <LemonSnack
                    type="pill"
                    onClick={() => {
                        setVisible(!visible)
                    }}
                    onClose={onRemove}
                >
                    <span title={label}>{midEllipsis(label, 32)}</span>
                </LemonSnack>
            </div>
        </Popover>
    )
}
