import './Today.scss'

import { Text, cn } from '@posthog/quill'

import type { NewsBriefApi } from 'products/today/frontend/generated/api.schemas'

import { TodayChange } from './TodayChange'
import { TodayNewsSectionLabel } from './TodayNewsSectionLabel'
import { TodaySparkline } from './TodaySparkline'

export function TodayNewsBriefs({ briefs }: { briefs: NewsBriefApi[] }): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<div />} className="flex flex-col gap-1.5">
            <TodayNewsSectionLabel>Also today</TodayNewsSectionLabel>
            <ul className="TodayNewsBriefs m-0 flex list-none flex-wrap items-center gap-x-5 gap-y-1.5 p-0">
                {briefs.map((brief) => (
                    <li key={brief.id} className="flex items-center gap-1.5">
                        <span className="text-foreground">
                            <span className="font-semibold tabular-nums" translate="no">
                                {brief.value.toLocaleString('en-US')}
                            </span>{' '}
                            <span>{brief.text}</span>
                        </span>
                        {brief.series.length > 1 ? (
                            <span className="h-3.5 w-10 shrink-0">
                                <TodaySparkline
                                    values={brief.series}
                                    labels={brief.series_labels}
                                    tone={brief.tone}
                                    emphasizeLast={3}
                                    fromZero
                                />
                            </span>
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
