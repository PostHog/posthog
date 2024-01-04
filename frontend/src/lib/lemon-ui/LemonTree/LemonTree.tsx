import './LemonTree.scss'

import { LemonTreeRow } from './LemonTreeRow'

export interface LemonTreeProps {
    children?: React.ReactNode
    className?: string
    items: LemonTreeItem[]
    depth?: number
}

interface LemonTreeItemBase {
    name: string
}

export type LemonTreeItem = LemonTreeItemFolder | LemonTreeItemLeaf

interface LemonTreeItemFolder extends LemonTreeItemBase {
    items: LemonTreeItemLeaf[]
}

interface LemonTreeItemLeaf extends LemonTreeItemBase {
    items?: never
}

export function LemonTree({ className = 'LemonTree__root rounded-lg', items, depth = 1 }: LemonTreeProps): JSX.Element {
    return (
        <ul className={`LemonTree ${className}`}>
            {items.map((item, index) => (
                <LemonTreeRow key={depth + '_' + index} item={item} depth={depth} />
            ))}
        </ul>
    )
}
