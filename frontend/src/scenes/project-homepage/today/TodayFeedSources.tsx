import { useActions, useValues } from 'kea'

import { Button, IconStack, IconStackItem } from '@posthog/quill'

import { todayLogic } from './todayLogic'
import { highlightIcon, reportIcon, type TodayRowIcon } from './todayRowIcons'

export function TodayFeedSources(): JSX.Element {
    const { feedSources, feedSource, forYouRows } = useValues(todayLogic)
    const { setFeedSource } = useActions(todayLogic)
    const options: { label: string; count: number; value: string | null; icon: TodayRowIcon | null }[] = [
        { label: 'All', count: forYouRows.rows.length, value: null, icon: null },
        ...feedSources.map(({ label, count, row }) => ({
            label,
            count,
            value: label,
            icon: row.kind === 'report' ? reportIcon(row.report) : highlightIcon(row.item),
        })),
    ]
    return (
        <nav className="TodayFeedSources" aria-label="Filter the feed">
            {options.map(({ label, count, value, icon }) => (
                <Button
                    key={label}
                    variant="link-muted"
                    size="sm"
                    aria-pressed={feedSource === value}
                    onClick={() => setFeedSource(value)}
                    data-attr="today-feed-source"
                >
                    <span className="TodayFeedSources__icon">
                        {icon && (
                            <IconStack>
                                <IconStackItem color={icon.color}>{icon.glyph}</IconStackItem>
                            </IconStack>
                        )}
                    </span>
                    <span className="TodayFeedSources__label">{label}</span>
                    <span className="TodayFeedSources__count" translate="no">
                        {count}
                    </span>
                </Button>
            ))}
        </nav>
    )
}
