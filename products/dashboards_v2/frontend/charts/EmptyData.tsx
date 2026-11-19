import { Text } from '@posthog/quill'

export function EmptyData({ message = 'No data' }: { message?: string }): JSX.Element {
    return (
        <div className="flex h-full items-center justify-center">
            <Text size="sm" variant="muted">
                {message}
            </Text>
        </div>
    )
}
