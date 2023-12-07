import { useValues } from 'kea'
import { Fade } from 'lib/components/Fade/Fade'
import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import { useRef } from 'react'

import { Toolbar } from './bar/Toolbar'
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
        <Fade visible={buttonVisible} className="toolbar-global-fade-container ph-no-capture posthog-3000">
            <Elements />
            <div id="button-toolbar" ref={ref} className="ph-no-capture posthog-3000" {...themeProps}>
                <FloatingContainerContext.Provider value={ref}>
                    <Toolbar />
                </FloatingContainerContext.Provider>
            </div>
            <HedgehogButton />
        </Fade>
    )
}
