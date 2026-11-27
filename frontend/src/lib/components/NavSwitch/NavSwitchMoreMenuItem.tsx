import { Menu } from '@base-ui/react/menu'
import { useActions, useValues } from 'kea'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { navSwitchLogic } from './navSwitchLogic'
import { useSwitchHintFocus } from './useSwitchHintFocus'

/** The old navigation's "More" menu entry for the new design. */
export function NavSwitchMoreMenuItem(): JSX.Element | null {
    const { switchAvailable, switchLabel, switchHintVisible } = useValues(navSwitchLogic)
    const { switchNav } = useActions(navSwitchLogic)
    const itemRef = useSwitchHintFocus<HTMLDivElement>()

    if (!switchAvailable) {
        return null
    }

    return (
        <Menu.Item
            ref={itemRef}
            onClick={() => switchNav('navbar_more_menu')}
            render={
                <ButtonPrimitive
                    menuItem
                    tooltip="You can try the new design from here any time."
                    tooltipPlacement="right"
                    // Undefined, not false, outside the hint, so hovering still shows the tooltip.
                    tooltipVisible={switchHintVisible || undefined}
                    data-attr="more-menu-nav-switch-button"
                >
                    {switchLabel}
                </ButtonPrimitive>
            }
        />
    )
}
