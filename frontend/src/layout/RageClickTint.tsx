import { useValues } from 'kea'
import { createPortal } from 'react-dom'

import { rageClickTintLogic } from './rageClickTintLogic'

export function RageClickTint(): JSX.Element {
    const { intensity } = useValues(rageClickTintLogic)

    return createPortal(
        <div
            aria-hidden="true"
            className="pointer-events-none fixed inset-0 z-[2147483647] bg-danger transition-opacity duration-1000 ease-linear motion-reduce:hidden"
            data-attr="rageclick-tint"
            style={{ opacity: intensity / 100 }}
        />,
        document.body
    )
}
