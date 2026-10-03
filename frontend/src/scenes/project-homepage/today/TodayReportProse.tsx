import clsx from 'clsx'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { shortenGitHubLinks } from './todayReportPresentation'

const TONES = {
    lead: 'text-sm leading-relaxed text-foreground [&_strong]:font-normal',
    plain: 'text-sm leading-relaxed text-foreground [&_strong]:font-normal',
    body: 'text-sm leading-relaxed text-foreground [&_strong]:font-semibold',
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
            className={clsx(
                TONES[tone],
                'text-pretty [&_a_svg]:hidden [&_a]:underline [&_a]:underline-offset-2 [&_code]:text-[0.9em] [&_li]:my-0.5 [&_p]:my-0 [&_p+p]:mt-3 [&_ul]:my-1 [&_ul]:ps-5',
                className
            )}
            disableImages="all"
            disableMentions
        >
            {shortenGitHubLinks(markdown)}
        </LemonMarkdown>
    )
}
