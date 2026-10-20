import { useActions, useValues } from 'kea'
import { RefObject, useEffect } from 'react'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'

import { navigation3000Logic } from '../../navigation-3000/navigationLogic'
import { PANEL_NAVBAR_COLLAPSE_THRESHOLD, PANEL_NAVBAR_DEFAULT_WIDTH, panelLayoutLogic } from '../panelLayoutLogic'

export function NavBarResizeHandle({
    containerRef,
    className,
}: {
    containerRef: RefObject<HTMLDivElement>
    className?: string
}): JSX.Element {
    const { toggleLayoutNavCollapsed, setNavbarWidth } = useActions(panelLayoutLogic)
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const { mobileLayout } = useValues(navigation3000Logic)
    const resizerLogicProps: ResizerLogicProps = {
        logicKey: 'panel-layout-navbar',
        placement: 'right',
        containerRef,
        persistent: true,
        closeThreshold: PANEL_NAVBAR_COLLAPSE_THRESHOLD,
        onToggleClosed: (closed) => toggleLayoutNavCollapsed(closed),
        onDoubleClick: () => toggleLayoutNavCollapsed(),
    }
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))
    const openWidth = Math.max(Math.round(desiredSize ?? PANEL_NAVBAR_DEFAULT_WIDTH), PANEL_NAVBAR_COLLAPSE_THRESHOLD)

    useEffect(() => {
        if (!isLayoutNavCollapsed && !mobileLayout) {
            setNavbarWidth(openWidth)
        }
    }, [openWidth, isLayoutNavCollapsed, mobileLayout, setNavbarWidth])

    return <Resizer {...resizerLogicProps} data-attr="tree-navbar-resizer" className={className} offset={0} />
}
