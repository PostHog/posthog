import { Button, Text } from '@posthog/quill'

export function QuillRetryText({ message, onRetry }: { message: string; onRetry: () => void }): JSX.Element {
    return (
        <Text size="xs" render={<p className="m-0" />}>
            {message}{' '}
            <Button variant="link" size="inline" onClick={onRetry}>
                Try again
            </Button>
        </Text>
    )
}
