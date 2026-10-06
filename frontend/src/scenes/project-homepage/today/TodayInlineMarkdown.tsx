import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { inlineSegments } from './todayProse'

export function TodayInlineMarkdown({ markdown }: { markdown: string }): JSX.Element {
    return (
        <>
            {inlineSegments(markdown).map((segment, index) => {
                switch (segment.kind) {
                    case 'code':
                        return (
                            <code key={index} className="text-[0.9em]">
                                {segment.text}
                            </code>
                        )
                    case 'link':
                        return (
                            <LinkPrimitive
                                key={index}
                                to={segment.href}
                                target="_blank"
                                className="underline underline-offset-2"
                            >
                                {segment.text}
                            </LinkPrimitive>
                        )
                    default:
                        return <span key={index}>{segment.text}</span>
                }
            })}
        </>
    )
}
