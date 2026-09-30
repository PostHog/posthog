import { useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { libraryLogic } from './libraryLogic'

interface LibraryCreateButtonProps {
    objectType: string
    /** Shown on the button. Without it the button is a small plus icon. */
    label?: string
}

/** Creates an object of one Library type. Types with several kinds (insights) open a menu of kinds. */
export function LibraryCreateButton({ objectType, label }: LibraryCreateButtonProps): JSX.Element | null {
    const { createItemsByType, objectTypeByValue } = useValues(libraryLogic)
    const items = createItemsByType[objectType] ?? []
    const typeLabel = objectTypeByValue[objectType]?.label.toLowerCase() ?? 'object'
    if (!items.length) {
        return null
    }
    const accessibleLabel = `New ${typeLabel}`
    const single = items.length === 1
    const button = label ? (
        <Button
            variant="primary"
            size="sm"
            render={single ? <LinkPrimitive to={items[0].href} /> : undefined}
            data-attr="library-new-object"
        >
            <IconPlus />
            <span>{label}</span>
        </Button>
    ) : (
        <Button
            size="icon-xs"
            aria-label={accessibleLabel}
            render={single ? <LinkPrimitive to={items[0].href} /> : undefined}
            data-attr={single ? 'library-new-object' : undefined}
        >
            <IconPlus />
        </Button>
    )

    const trigger = single ? button : <DropdownMenuTrigger render={button} />
    const control = label ? (
        trigger
    ) : (
        <Tooltip>
            <TooltipTrigger delay={0} render={trigger} />
            <TooltipContent>{accessibleLabel}</TooltipContent>
        </Tooltip>
    )

    if (single) {
        return control
    }
    return (
        <DropdownMenu>
            {control}
            <DropdownMenuContent align="end">
                {items.map((item) => (
                    <DropdownMenuItem
                        key={item.href}
                        render={<LinkPrimitive to={item.href} />}
                        data-attr="library-new-object"
                    >
                        {item.path.split('/').pop() ?? item.path}
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
