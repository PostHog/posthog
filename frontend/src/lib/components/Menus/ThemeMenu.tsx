import { DropdownMenuSubContentProps } from '@radix-ui/react-dropdown-menu'
import { useActions, useValues } from 'kea'

import { IconDay, IconLaptop, IconNight, IconPalette } from '@posthog/icons'

import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { UserTheme } from '~/types'

export function ThemeMenu(props: DropdownMenuSubContentProps): JSX.Element {
    const { themeMode } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)
    const { customCssEnabled } = useValues(themeLogic)

    function handleThemeChange(theme: UserTheme): void {
        updateUser({ theme_mode: theme })
    }

    return (
        <DropdownMenuSub>
            <DropdownMenuSubTrigger asChild>
                <ButtonPrimitive menuItem>
                    <IconPalette />
                    Color theme
                    <div className="ml-auto flex items-center gap-1">
                        <LemonTag>{themeMode}</LemonTag>
                        <MenuOpenIndicator intent="sub" className="ml-auto" />
                    </div>
                </ButtonPrimitive>
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent {...props}>
                <DropdownMenuGroup>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive
                            active={themeMode === 'light'}
                            onClick={() => handleThemeChange('light')}
                            menuItem
                        >
                            <IconDay />
                            Light mode
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive
                            active={themeMode === 'dark'}
                            onClick={() => handleThemeChange('dark')}
                            menuItem
                        >
                            <IconNight />
                            Dark mode
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive
                            active={themeMode === 'system'}
                            onClick={() => handleThemeChange('system')}
                            menuItem
                        >
                            <IconLaptop />
                            Sync with system
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    {customCssEnabled && (
                        <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem asChild>
                                <Link to={urls.customCss()} buttonProps={{ menuItem: true }}>
                                    <IconPalette />
                                    Edit custom CSS
                                </Link>
                            </DropdownMenuItem>
                        </>
                    )}
                </DropdownMenuGroup>
            </DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}
