import { DataModelingNodeType } from '~/types'

import { NODE_TYPE_TAG_SETTINGS } from './nodeStyles'

/** The type mark drawn on a lineage node, and repeated in the legend. */
export function NodeTypeTag({ type }: { type: DataModelingNodeType }): JSX.Element {
    const { label, color } = NODE_TYPE_TAG_SETTINGS[type]
    return (
        <span
            className="text-[10px] lowercase tracking-wide px-1 rounded border-1 whitespace-nowrap"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                color,
                backgroundColor: `color-mix(in srgb, ${color} 20%, transparent)`,
                borderColor: `color-mix(in srgb, ${color} 80%, transparent)`,
            }}
        >
            {label}
        </span>
    )
}
