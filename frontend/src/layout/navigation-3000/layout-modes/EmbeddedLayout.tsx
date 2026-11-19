import { ReactNode } from 'react'

import { SimpleLayoutFrame } from '../components/SimpleLayoutFrame'

export function EmbeddedLayout({ children }: { children: ReactNode }): JSX.Element {
    return <SimpleLayoutFrame mainClassName="@container/main-content min-h-screen p-4">{children}</SimpleLayoutFrame>
}
