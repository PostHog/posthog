import { Text } from '@posthog/quill'

export function QuillModelErrorText({ error }: { error: string }): JSX.Element {
    return (
        <Text
            size="xs"
            variant="destructive"
            className="m-0 max-h-64 overflow-auto font-mono break-words whitespace-pre-wrap"
        >
            {error}
        </Text>
    )
}
