import { IconSearch } from '@posthog/icons'
import type { Meta } from '@storybook/react'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'

// import { Button } from './Button'
import { ButtonGroupPrimitive, ButtonPrimitive } from './ButtonPrimitives'

const meta = {
    title: 'UI/ButtonPrimitive',
    component: ButtonPrimitive as any,
    tags: ['autodocs'],
} satisfies Meta<typeof ButtonPrimitive>

export default meta

export function Default(): JSX.Element {
    return (
        <div className="flex flex-col gap-4 max-w-lg">
            <ButtonPrimitive variant="outline" size="base">
                Button base
            </ButtonPrimitive>

            <ButtonPrimitive variant="outline" size="base">
                <IconSearch />
                Button base
            </ButtonPrimitive>

            <ButtonPrimitive variant="outline" size="base" className="max-w-[100px]">
                <IconSearch />
                <span className="truncate">Button base truncate</span>
            </ButtonPrimitive>

            <ButtonPrimitive variant="outline" size="base" iconOnly>
                <IconSearch />
            </ButtonPrimitive>

            <ButtonGroupPrimitive size="base" variant="outline">
                <ButtonPrimitive
                    onClick={() => {
                        alert('clicked')
                    }}
                    tooltip="Tooltip"
                >
                    Button1
                </ButtonPrimitive>
                <ButtonPrimitive href="#" tooltip="Tooltip">
                    Link
                </ButtonPrimitive>
                <ButtonPrimitive iconOnly tooltip="Tooltip">
                    <IconSearch />
                </ButtonPrimitive>
                <ButtonPrimitive iconOnly tooltip="Tooltip">
                    <IconSearch />
                </ButtonPrimitive>
            </ButtonGroupPrimitive>

            <ButtonGroupPrimitive size="base" variant="outline" groupVariant="side-action-group">
                <ButtonPrimitive href="#" sideActionLeft tooltip="Tooltip">
                    Side action group
                </ButtonPrimitive>
                <ButtonPrimitive iconOnly sideActionRight tooltip="Tooltip">
                    <IconSearch />
                </ButtonPrimitive>
            </ButtonGroupPrimitive>

            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <ButtonPrimitive variant="outline" size="base" tooltip="Tooltip">
                        <IconSearch />
                        is all dropdown
                    </ButtonPrimitive>
                </DropdownMenuTrigger>

                <DropdownMenuContent loop align="start">
                    <DropdownMenuLabel>Section 1</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive size="base" menuItem>
                            Item 1
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive size="base" menuItem>
                            Item 2
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>

            <DropdownMenu>
                <ButtonGroupPrimitive size="base" variant="outline" fullWidth>
                    <ButtonPrimitive href="#" menuItem>
                        Link here, dropdown on the right
                    </ButtonPrimitive>
                    <DropdownMenuTrigger asChild>
                        <ButtonPrimitive variant="outline" size="base" iconOnly>
                            <IconSearch />
                        </ButtonPrimitive>
                    </DropdownMenuTrigger>
                </ButtonGroupPrimitive>

                <DropdownMenuContent loop align="start">
                    <DropdownMenuLabel>Section 1</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive size="base" menuItem>
                            Item 1
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive size="base" menuItem>
                            Item 2
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>

            <DropdownMenu>
                <ButtonGroupPrimitive size="base" variant="default" fullWidth>
                    <ButtonPrimitive href="#" menuItem>
                        Link here, dropdown on the right
                    </ButtonPrimitive>
                    <DropdownMenuTrigger asChild>
                        <ButtonPrimitive variant="outline" size="base" iconOnly>
                            <IconSearch />
                        </ButtonPrimitive>
                    </DropdownMenuTrigger>
                </ButtonGroupPrimitive>

                <DropdownMenuContent loop align="start">
                    <DropdownMenuLabel>Section 1</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive size="base" menuItem>
                            Item 1
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive size="base" menuItem>
                            Item 2
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}

export function Sizes(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-4">
                <ButtonPrimitive size="sm">Small button</ButtonPrimitive>

                <ButtonPrimitive size="sm">
                    <IconSearch />
                    Small button
                </ButtonPrimitive>

                <ButtonPrimitive size="sm" iconOnly>
                    <IconSearch />
                </ButtonPrimitive>
            </div>
            <div className="flex flex-col gap-4">
                <ButtonPrimitive>Base button</ButtonPrimitive>

                <ButtonPrimitive>
                    <IconSearch />
                    Base button
                </ButtonPrimitive>

                <ButtonPrimitive iconOnly>
                    <IconSearch />
                </ButtonPrimitive>
            </div>
            <div className="flex flex-col gap-4">
                <ButtonPrimitive size="lg">Large button</ButtonPrimitive>

                <ButtonPrimitive size="lg">
                    <IconSearch />
                    Large button
                </ButtonPrimitive>

                <ButtonPrimitive size="lg" iconOnly>
                    <IconSearch />
                </ButtonPrimitive>
            </div>
        </div>
    )
}
