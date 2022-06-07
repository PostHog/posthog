import React from 'react'
import { LemonTag } from '../LemonTag/LemonTag'

export function WarningTag({ children = null }: { children: React.ReactNode }): JSX.Element {
    return (
        <LemonTag type="warning" style={{ marginLeft: 6, lineHeight: '1.4em' }}>
            <span>{children}</span>
        </LemonTag>
    )
}
