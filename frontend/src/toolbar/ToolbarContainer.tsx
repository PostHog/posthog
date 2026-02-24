import { useValues } from 'kea'
import { useRef } from 'react'

import { Fade } from 'lib/components/Fade/Fade'
import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'

import { Toolbar } from './bar/Toolbar'
import { ToolbarFixedZones } from './bar/ToolbarFixedZones'
import { toolbarLogic } from './bar/toolbarLogic'
import { Elements } from './elements/Elements'
import { HedgehogButton } from './hedgehog/HedgehogButton'
import { toolbarConfigLogic } from './toolbarConfigLogic'

export function ToolbarContainer(): JSX.Element {
    const { buttonVisible } = useValues(toolbarConfigLogic)
    const { theme } = useValues(toolbarLogic)

    // KLUDGE: if we put theme directly on the div then
    // linting and typescript complain about it not being
    // a valid attribute. So we put it in a variable and
    // spread it in. 🤷‍
    const themeProps = { theme }

    const ref = useRef<HTMLDivElement | null>(null)

    return (
        <Fade visible={buttonVisible} className="toolbar-global-fade-container">
            <FloatingContainerContext.Provider value={ref}>
                <Elements />
                <ToolbarFixedZones />
                <div id="button-toolbar" {...themeProps}>
                    <Toolbar />
                </div>
                <HedgehogButton />
                <div ref={ref} className="fixed inset-0 pointer-events-none z-[2147483647] [&>*]:pointer-events-auto" />
            </FloatingContainerContext.Provider>
        </Fade>
    )
}
