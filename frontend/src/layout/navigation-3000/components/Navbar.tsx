import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useRef } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { navigation3000Logic } from '../navigationLogic'
import { NavbarBottom } from './NavbarBottom'
import { NavbarButton } from './NavbarButton'

export function Navbar(): JSX.Element {
    const { theme } = useValues(themeLogic)
    const { isNavShown, isSidebarShown, activeNavbarItemId, navbarItems, mobileLayout } = useValues(navigation3000Logic)
    const { toggleNavCollapsed, hideNavOnMobile, showSidebar, hideSidebar } = useActions(navigation3000Logic)
    const { featureFlags } = useValues(featureFlagLogic)

    const containerRef = useRef<HTMLDivElement | null>(null)

    return (
        <>
            <nav className={clsx('Navbar3000', !isNavShown && 'Navbar3000--hidden')} ref={containerRef}>
                <div
                    className="Navbar3000__content"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={theme?.sidebarStyle}
                >
                    <ScrollableShadows innerClassName="Navbar3000__top" direction="vertical">
                        {navbarItems.map((section, index) => (
                            <ul key={index}>
                                {section.map((item) =>
                                    item.featureFlag && !featureFlags[item.featureFlag] ? null : (
                                        <NavbarButton
                                            key={item.identifier}
                                            title={item.label}
                                            identifier={item.identifier}
                                            icon={item.icon}
                                            sideAction={item.sideAction}
                                            tag={item.tag}
                                            to={'to' in item ? item.to : undefined}
                                            onClick={() => {
                                                if ('logic' in item) {
                                                    if (activeNavbarItemId === item.identifier && !isSidebarShown) {
                                                        hideSidebar()
                                                    } else {
                                                        showSidebar(item.identifier)
                                                    }
                                                }
                                                item.onClick?.()
                                            }}
                                            active={activeNavbarItemId === item.identifier && isSidebarShown}
                                            tooltipDocLink={item.tooltipDocLink}
                                        />
                                    )
                                )}
                            </ul>
                        ))}
                    </ScrollableShadows>
                    <NavbarBottom />
                </div>
                {!mobileLayout && (
                    <Resizer
                        logicKey="navbar"
                        placement="right"
                        containerRef={containerRef}
                        closeThreshold={100}
                        onToggleClosed={(shouldBeClosed) => toggleNavCollapsed(shouldBeClosed)}
                        onDoubleClick={() => toggleNavCollapsed()}
                    />
                )}
            </nav>
            {mobileLayout && (
                <div
                    className={clsx('Navbar3000__overlay', !isNavShown && 'Navbar3000--hidden')}
                    onClick={() => hideNavOnMobile()}
                />
            )}
        </>
    )
}
