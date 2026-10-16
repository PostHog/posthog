import { Text } from '@posthog/quill'

const LINES = [
    { command: true, text: '$ posthog-cli login' },
    { command: false, text: 'Logged in to Example project' },
    { command: true, text: '$ posthog-cli api search flag' },
    { command: false, text: 'feature-flag-get-all' },
    { command: true, text: "$ posthog-cli api call feature-flag-get-all '{}'" },
]

export function CliIllustration(): JSX.Element {
    return (
        <div className="flex h-full flex-col gap-1 overflow-hidden rounded-tl-md border-t border-l border-border bg-background p-2 font-mono">
            {LINES.map(({ command, text }) => (
                <Text key={text} size="xxs" variant={command ? 'default' : 'muted'} className="truncate">
                    {text}
                </Text>
            ))}
        </div>
    )
}
