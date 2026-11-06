import { Card, CardContent, Text } from '@posthog/quill'

const LEADING_NUMBER = /^(\d[\d,.]*%?)\s+(.+)$/

export function TodayNewsBriefs({ briefs }: { briefs: string[] }): JSX.Element {
    return (
        <Card size="sm">
            <CardContent>
                <ul className="m-0 flex list-none flex-col gap-4 p-0 @2xl:flex-row">
                    {briefs.map((brief) => {
                        const match = LEADING_NUMBER.exec(brief)
                        return (
                            <li key={brief} className="flex flex-1 flex-col gap-0.5">
                                {match ? (
                                    <span className="text-2xl font-semibold tracking-tight tabular-nums" translate="no">
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
            </CardContent>
        </Card>
    )
}
