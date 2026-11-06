import { Fragment } from 'react'

import { Text } from '@posthog/quill'

const LEADING_NUMBER = /^(\d[\d,.]*%?)\s+(.+)$/

export function TodayNewsBriefs({ briefs }: { briefs: string[] }): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<p />} className="m-0 flex flex-wrap gap-x-2 gap-y-1">
            <span>Also today:</span>
            {briefs.map((brief, index) => {
                const match = LEADING_NUMBER.exec(brief)
                return (
                    <Fragment key={brief}>
                        {index > 0 ? <span aria-hidden>·</span> : null}
                        <span className="text-foreground">
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
                        </span>
                    </Fragment>
                )
            })}
        </Text>
    )
}
