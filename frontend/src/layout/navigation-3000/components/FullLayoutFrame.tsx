import { useValues } from 'kea'
import { CSSProperties, ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'

import { ProjectDragAndDropProvider } from '~/layout/panel-layout/ProjectTree/ProjectDragAndDropContext'

import { themeLogic } from '../themeLogic'

/** Outer frame for the layouts with the app chrome. */
export function FullLayoutFrame({
    className,
    style,
    children,
}: {
    className?: string
    style?: CSSProperties
    children: ReactNode
}): JSX.Element {
    const { theme } = useValues(themeLogic)

    return (
        <>
            {/* eslint-disable-next-line react/forbid-elements */}
            <a
                href="#main-content"
                className="sr-only focus:not-sr-only focus:fixed focus:z-top focus:top-4 focus:left-4 focus:p-4 focus:bg-white focus:dark:bg-gray-800 focus:rounded focus:shadow-lg"
                tabIndex={0}
            >
                Skip to content
            </a>
            <div
                className={cn('app-layout bg-surface-tertiary', className)}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ ...theme?.mainStyle, ...style } as CSSProperties}
            >
                <ProjectDragAndDropProvider>{children}</ProjectDragAndDropProvider>
            </div>
        </>
    )
}
