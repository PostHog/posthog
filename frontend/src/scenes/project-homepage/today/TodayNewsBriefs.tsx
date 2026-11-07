import { Text, cn } from '@posthog/quill'

import type { NewsBriefApi } from 'products/today/frontend/generated/api.schemas'

import { TodayChange } from './TodayChange'
import { TodayNewsChart } from './TodayNewsChart'

export function TodayNewsBriefs({ briefs }: { briefs: NewsBriefApi[] }): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<div />} className="flex flex-col gap-1.5">
            <span className="font-medium">Also today</span>
            <ul className="TodayNewsBriefs m-0 flex list-none flex-wrap items-center gap-x-5 gap-y-1.5 p-0">
                {briefs.map((brief) => (
                    <li key={brief.id} className="flex items-center gap-1.5">
                        <span className="text-foreground">
                            <span className="font-semibold tabular-nums" translate="no">
                                {brief.value.toLocaleString('en-US')}
                            </span>{' '}
                            {brief.text}
                        </span>
                        {brief.series.length > 1 ? (
                            <TodayNewsChart
                                values={brief.series}
                                labels={brief.series_labels}
                                tone={brief.tone}
                                emphasizeLast={3}
                                className="h-3.5 w-10 shrink-0"
                            />
                        ) : null}
                        {brief.is_new ? (
                            <span className={cn('font-medium', brief.tone === 'risk' && 'text-danger')}>New</span>
                        ) : (
                            <TodayChange change={brief.change} tone={brief.tone} />
                        )}
                    </li>
                ))}
            </ul>
        </Text>
    )
}
