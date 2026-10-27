import { ReactNode } from 'react'

import { MinimalNavigation } from '../components/MinimalNavigation'
import { SimpleLayoutFrame } from '../components/SimpleLayoutFrame'

export function ZenLayout({ children }: { children: ReactNode }): JSX.Element {
    return (
        <SimpleLayoutFrame nav={<MinimalNavigation />} mainClassName="@container/main-content p-4">
            {children}
        </SimpleLayoutFrame>
    )
}
