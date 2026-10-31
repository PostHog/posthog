import { useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { navigateToHref } from 'lib/utils/navigateToHref'

import { libraryLogic } from './libraryLogic'

interface QuillLibraryCreateButtonProps {
    objectType: string
    /** Shown on the button. Without it the button is a small plus icon. */
    label?: string
}

export function QuillLibraryCreateButton({ objectType, label }: QuillLibraryCreateButtonProps): JSX.Element | null {
    const { createItemsByType, objectTypeByValue } = useValues(libraryLogic)
    const items = createItemsByType[objectType] ?? []
    const typeLabel = objectTypeByValue[objectType]?.label.toLowerCase() ?? 'object'
    if (!items.length) {
        return null
    }
    const newLabel = `New ${typeLabel}`
    const buttonProps = label ? ({ variant: 'primary' } as const) : ({ variant: 'default', size: 'icon-sm' } as const)
    const content = (
        <>
            <IconPlus />
            {label}
        </>
    )

    if (items.length === 1) {
        return (
            <Button
                {...buttonProps}
                render={<LinkPrimitive to={items[0].href} />}
                aria-label={newLabel}
                tooltip={label ? undefined : newLabel}
                data-attr="library-new-object"
            >
                {content}
            </Button>
        )
    }
    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button {...buttonProps} aria-label={newLabel} />}>
                {content}
            </DropdownMenuTrigger>
            <DropdownMenuContent className="min-w-40">
                {items.map((item) => (
                    <DropdownMenuItem
                        key={item.href}
                        onClick={() => navigateToHref(item.href)}
                        data-attr="library-new-object"
                    >
                        {item.path.split('/').pop() ?? item.path}
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
