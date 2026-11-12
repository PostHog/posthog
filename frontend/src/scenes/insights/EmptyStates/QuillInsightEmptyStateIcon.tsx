import { IconStack, IconStackItem } from '@posthog/quill'

export function QuillInsightEmptyStateIcon({ icon }: { icon: JSX.Element }): JSX.Element {
    return (
        <IconStack>
            <IconStackItem color="var(--color-product-product-analytics-light)">{icon}</IconStackItem>
        </IconStack>
    )
}
