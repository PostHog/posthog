import { Text } from '@posthog/quill'

const LEADING_NUMBER = /^(\d[\d,.]*%?)\s+(.+)$/

export function TodayNewsBriefs({ briefs }: { briefs: string[] }): JSX.Element {
    return (
        <section className="flex flex-col gap-1.5 border-t pt-3">
            <Text size="xs" variant="muted" render={<h4 />} className="m-0">
                Also today
            </Text>
            <ul className="m-0 flex list-none flex-col gap-1 p-0">
                {briefs.map((brief) => {
                    const match = LEADING_NUMBER.exec(brief)
                    return (
                        <li key={brief}>
                            <Text size="xs" render={<span />}>
                                {match ? (
                                    <>
                                        <span className="font-semibold tabular-nums" translate="no">
                                            {match[1]}
                                        </span>{' '}
                                        {match[2]}
                                    </>
                                ) : (
                                    brief
                                )}
                            </Text>
                        </li>
                    )
                })}
            </ul>
        </section>
    )
}
