import { Menu } from '@base-ui/react/menu'
import { useActions, useValues } from 'kea'

import { IconDay, IconLaptop, IconNight, IconPalette } from '@posthog/icons'

import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { UserTheme } from '~/types'

export function ThemeMenu(): JSX.Element {
    const { themeMode } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)
    const { customCssEnabled } = useValues(themeLogic)

    function handleThemeChange(theme: UserTheme): void {
        updateUser({ theme_mode: theme })
    }

    return (
        <Menu.SubmenuRoot>
            <Menu.SubmenuTrigger
                render={
                    <ButtonPrimitive menuItem>
                        <IconPalette />
                        Color theme
                        <div className="ml-auto flex items-center gap-1">
                            <LemonTag>{themeMode}</LemonTag>
                            <MenuOpenIndicator intent="sub" className="ml-auto" />
                        </div>
                    </ButtonPrimitive>
                }
            />
            <Menu.Portal>
                <Menu.Positioner className="z-[var(--z-popover)]" collisionPadding={{ top: 50, bottom: 50 }}>
                    <Menu.Popup className="primitive-menu-content">
                        <div className="primitive-menu-content-inner flex flex-col gap-px p-1">
                            <Menu.Item
                                onClick={() => handleThemeChange('light')}
                                render={
                                    <ButtonPrimitive active={themeMode === 'light'} menuItem>
                                        <IconDay />
                                        Light mode
                                    </ButtonPrimitive>
                                }
                            />
                            <Menu.Item
                                onClick={() => handleThemeChange('dark')}
                                render={
                                    <ButtonPrimitive active={themeMode === 'dark'} menuItem>
                                        <IconNight />
                                        Dark mode
                                    </ButtonPrimitive>
                                }
                            />
                            <Menu.Item
                                onClick={() => handleThemeChange('system')}
                                render={
                                    <ButtonPrimitive active={themeMode === 'system'} menuItem>
                                        <IconLaptop />
                                        Sync with system
                                    </ButtonPrimitive>
                                }
                            />
                            {customCssEnabled && (
                                <Menu.Item
                                    render={(props) => (
                                        <Link {...props} to={urls.customCss()} buttonProps={{ menuItem: true }}>
                                            <IconPalette />
                                            Edit custom CSS
                                        </Link>
                                    )}
                                />
                            )}
                        </div>
                    </Menu.Popup>
                </Menu.Positioner>
            </Menu.Portal>
        </Menu.SubmenuRoot>
    )
}
