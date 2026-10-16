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
            <div className="flex items-center gap-1">
                <Text size="xxs">$</Text>
                <span className="h-3 w-1.5 bg-current text-foreground group-has-[a:hover]/card:animate-pulse group-has-[a:focus-visible]/card:animate-pulse motion-reduce:animate-none" />
            </div>
        </div>
    )
}
