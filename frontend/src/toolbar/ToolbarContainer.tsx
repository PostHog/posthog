import clsx from 'clsx'
import { useValues } from 'kea'
import { Fade } from 'lib/components/Fade/Fade'
import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import { useRef } from 'react'

import { Toolbar } from './bar/Toolbar'
import { ToolbarFixedZones } from './bar/ToolbarFixedZones'
import { toolbarLogic } from './bar/toolbarLogic'
import { Elements } from './elements/Elements'
import { HedgehogButton } from './hedgehog/HedgehogButton'
import { toolbarConfigLogic } from './toolbarConfigLogic'

export function ToolbarContainer(): JSX.Element {
    const { buttonVisible } = useValues(toolbarConfigLogic)
    const { theme } = useValues(toolbarLogic)
    const ref = useRef<HTMLDivElement | null>(null)

    return (
        <Fade visible={buttonVisible} className="toolbar-global-fade-container ph-no-capture">
            <Elements />
            <ToolbarFixedZones />
            <div
                id="button-toolbar"
                ref={ref}
                className={clsx('ph-no-capture', theme === 'dark' ? 'theme-dark' : 'theme-light')}
            >
                <FloatingContainerContext.Provider value={ref}>
                    <Toolbar />
                </FloatingContainerContext.Provider>
            </div>
            <HedgehogButton />
        </Fade>
    )
}
