import { IconStack, IconStackItem } from '@posthog/quill'

export function QuillInsightEmptyStateIcon({
    icon,
    color = 'var(--color-product-product-analytics-light)',
}: {
    icon: JSX.Element
    color?: string
}): JSX.Element {
    return (
        <IconStack>
            <IconStackItem color={color}>{icon}</IconStackItem>
        </IconStack>
    )
}
