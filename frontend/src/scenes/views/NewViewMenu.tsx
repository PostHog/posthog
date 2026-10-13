import { useActions } from 'kea'

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    ItemContent,
    ItemDescription,
    ItemTitle,
} from '@posthog/quill'

import { newViewLogic } from './newViewLogic'
import { VIEW_TYPES } from './viewsUtils'
import { ViewTypeIcon } from './ViewTypeIcon'

interface NewViewMenuProps {
    /** The element that opens the menu, such as a quill `Button`. The menu merges its own props onto it. */
    trigger: JSX.Element
    children?: React.ReactNode
}

/** Asks which type of view to create, then hands off to that type's own create flow. */
export function NewViewMenu({ trigger, children }: NewViewMenuProps): JSX.Element {
    const { pickNewViewType } = useActions(newViewLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={trigger}>{children}</DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-72">
                {VIEW_TYPES.map((info) => (
                    <DropdownMenuItem
                        key={info.type}
                        className="h-auto items-start py-1.5 whitespace-normal [&>svg]:mt-1.5"
                        onClick={() => pickNewViewType(info.type)}
                        data-attr={`views-new-${info.type}`}
                    >
                        <ViewTypeIcon type={info.type} />
                        <ItemContent variant="menuItem">
                            <ItemTitle>{info.label}</ItemTitle>
                            <ItemDescription>{info.description}</ItemDescription>
                        </ItemContent>
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
