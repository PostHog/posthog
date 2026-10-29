import { ReactNode } from 'react'

import { SimpleLayoutFrame } from '../components/SimpleLayoutFrame'

export function BareLayout({ children }: { children: ReactNode }): JSX.Element {
    return <SimpleLayoutFrame>{children}</SimpleLayoutFrame>
}
