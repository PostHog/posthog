import { useValues } from 'kea'
import { CSSProperties, ReactNode } from 'react'

import { themeLogic } from '../themeLogic'

/** Outer frame for the layouts without app chrome. */
export function SimpleLayoutFrame({
    nav,
    mainClassName,
    children,
}: {
    nav?: ReactNode
    mainClassName?: string
    children: ReactNode
}): JSX.Element {
    const { theme } = useValues(themeLogic)

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div
            className="Navigation3000 flex-col"
            style={
                {
                    ...theme?.mainStyle,
                    // MinimalNavigation sits above the scene, so the fixed settings nav must clear it.
                    ...(nav && {
                        '--settings-nav-top': 'calc(var(--minimal-navigation-height) + var(--scene-padding))',
                    }),
                } as CSSProperties
            }
        >
            {nav}
            <main className={mainClassName}>{children}</main>
        </div>
    )
}
