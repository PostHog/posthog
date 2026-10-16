import { Text } from '@posthog/quill'

const LINES = [
    { command: true, text: '$ posthog-cli login' },
    { command: false, text: 'Logged in' },
    { command: true, text: '$ posthog-cli api tools' },
    { command: false, text: 'execute-sql' },
    { command: false, text: 'feature-flag-get-all' },
]

export function CliIllustration(): JSX.Element {
    return (
        <div className="flex h-full flex-col gap-1 overflow-hidden rounded-tl-md border-t border-l border-border bg-background p-2 font-mono">
            {LINES.map(({ command, text }) => (
                <Text key={text} size="xxs" variant={command ? 'default' : 'muted'} className="whitespace-nowrap">
                    {text}
                </Text>
            ))}
        </div>
    )
}
