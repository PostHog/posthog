import { Text } from '@posthog/quill'

const LEADING_NUMBER = /^(\d[\d,.]*%?)\s+(.+)$/

export function TodayNewsBriefs({ briefs }: { briefs: string[] }): JSX.Element {
    return (
        <ul className="m-0 flex list-none flex-col gap-4 border-t p-0 pt-4 @2xl:flex-row">
            {briefs.map((brief) => {
                const match = LEADING_NUMBER.exec(brief)
                return (
                    <li key={brief} className="flex flex-1 items-baseline gap-2">
                        {match ? (
                            <span className="text-xl font-semibold tracking-tight tabular-nums" translate="no">
                                {match[1]}
                            </span>
                        ) : null}
                        <Text size="xs" variant="muted" render={<span />} className="text-pretty">
                            {match ? match[2] : brief}
                        </Text>
                    </li>
                )
            })}
        </ul>
    )
}
