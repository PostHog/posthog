import './LemonTreeRow.scss'

import { IconDatabase } from '@posthog/icons'
import clsx from 'clsx'

import { IconChevronRight } from '../icons'
import { LemonTree, LemonTreeItem } from './LemonTree'

export interface LemonTreeRowProps {
    item: LemonTreeItem
    depth: number
}

export function LemonTreeRow({ item, depth }: LemonTreeRowProps): JSX.Element {
    const { name, items } = item

    const isFolder = items !== undefined

    return (
        <li>
            <div className={clsx('LemonTreeRow', isFolder ? 'font-bold' : '')}>
                {items ? <IconChevronRight className="mr-2" /> : <IconDatabase className="mr-2" />}
                {name}
            </div>
            {items && <LemonTree className={`ml-${7 * depth}`} items={items} depth={depth * 2} />}
        </li>
    )
}
