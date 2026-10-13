import { useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

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
    const buttonProps = label
        ? { type: 'primary' as const, size: 'small' as const, icon: <IconPlus />, children: label }
        : { size: 'xsmall' as const, icon: <IconPlus />, tooltip: `New ${typeLabel}` }

    if (items.length === 1) {
        return (
            <LemonButton
                {...buttonProps}
                to={items[0].href}
                aria-label={`New ${typeLabel}`}
                data-attr="library-new-object"
            />
        )
    }
    return (
        <LemonMenu
            items={items.map((item) => ({
                label: item.path.split('/').pop() ?? item.path,
                to: item.href,
                'data-attr': 'library-new-object',
            }))}
        >
            <LemonButton {...buttonProps} aria-label={`New ${typeLabel}`} />
        </LemonMenu>
    )
}
