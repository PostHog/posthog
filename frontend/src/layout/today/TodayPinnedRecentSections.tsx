import { Fragment } from 'react'

import { HrefPin } from './sidebar/hrefPins'
import { SidebarRowEnter } from './sidebar/SidebarRowEnter'
import { SidebarSection } from './sidebar/SidebarSection'

export type TodayPinnedRecentSection = 'pinned' | 'recents'

export function TodayPinnedRecentSections<P extends HrefPin<string>, R extends { href: string }>({
    pins,
    recents,
    renderPin,
    renderRecent,
    isSectionOpen,
    onToggleSection,
    dataAttrPrefix,
}: {
    pins: P[]
    recents: R[]
    renderPin: (pin: P) => JSX.Element
    renderRecent: (recent: R) => JSX.Element
    isSectionOpen: (section: TodayPinnedRecentSection) => boolean
    onToggleSection: (section: TodayPinnedRecentSection) => void
    dataAttrPrefix: string
}): JSX.Element {
    return (
        <>
            {pins.length > 0 && (
                <SidebarSection
                    label="Pinned"
                    open={isSectionOpen('pinned')}
                    count={pins.length}
                    showCount={false}
                    onToggle={() => onToggleSection('pinned')}
                    divider
                    dataAttr={`${dataAttrPrefix}-section-pinned`}
                >
                    {pins.map((pin) => (
                        <SidebarRowEnter key={pin.key} pinKey={pin.key}>
                            {renderPin(pin)}
                        </SidebarRowEnter>
                    ))}
                </SidebarSection>
            )}
            {recents.length > 0 && (
                <SidebarSection
                    label="Recents"
                    open={isSectionOpen('recents')}
                    count={recents.length}
                    showCount={false}
                    onToggle={() => onToggleSection('recents')}
                    divider
                    dataAttr={`${dataAttrPrefix}-section-recents`}
                >
                    {recents.map((recent) => (
                        <Fragment key={recent.href}>{renderRecent(recent)}</Fragment>
                    ))}
                </SidebarSection>
            )}
        </>
    )
}
