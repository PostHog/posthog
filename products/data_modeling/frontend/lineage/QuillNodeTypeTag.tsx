import { DataModelingNodeType } from '~/types'

import { NODE_TYPE_TAG_SETTINGS, QUILL_NODE_TYPE_COLORS } from './nodeStyles'

export function QuillNodeTypeTag({ type }: { type: DataModelingNodeType }): JSX.Element {
    const color = QUILL_NODE_TYPE_COLORS[type]
    return (
        <span
            className="rounded border px-1 text-xxs whitespace-nowrap lowercase tracking-wide"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                color,
                backgroundColor: `color-mix(in srgb, ${color} 12%, transparent)`,
                borderColor: `color-mix(in srgb, ${color} 50%, transparent)`,
            }}
        >
            {NODE_TYPE_TAG_SETTINGS[type].label}
        </span>
    )
}
