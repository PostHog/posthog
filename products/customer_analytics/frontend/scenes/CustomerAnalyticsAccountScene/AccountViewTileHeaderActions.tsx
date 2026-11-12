import { type ReactNode, useContext } from 'react'
import { createPortal } from 'react-dom'

import { accountViewTileHeaderContext } from './accountViewTileHeaderContext'

export function AccountViewTileHeaderActions({ children }: { children: ReactNode }): JSX.Element | null {
    const target = useContext(accountViewTileHeaderContext)
    if (target === undefined) {
        return <div className="flex flex-wrap items-center justify-end gap-2">{children}</div>
    }
    return target ? createPortal(children, target) : null
}
