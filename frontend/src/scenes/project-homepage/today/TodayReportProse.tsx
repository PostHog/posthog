import clsx from 'clsx'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

const TONES = {
    hero: 'text-xl leading-snug font-medium text-foreground',
    body: 'text-sm leading-relaxed text-muted-foreground',
}

export function TodayReportProse({
    markdown,
    tone,
    className,
}: {
    markdown: string
    tone: keyof typeof TONES
    className?: string
}): JSX.Element {
    return (
        <LemonMarkdown
            className={clsx(TONES[tone], 'text-pretty [&_strong]:font-semibold [&_strong]:text-foreground', className)}
            disableImages="all"
            disableMentions
        >
            {markdown}
        </LemonMarkdown>
    )
}
