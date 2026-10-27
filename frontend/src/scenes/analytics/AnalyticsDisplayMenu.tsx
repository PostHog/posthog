import { useActions, useValues } from 'kea'

import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { AnalyticsListDisplayConfiguration } from '~/queries/schema/schema-general'

import { analyticsListLogic } from './analyticsListLogic'

type AnalyticsSort = NonNullable<AnalyticsListDisplayConfiguration['default_sort']>

const SORT_OPTIONS: { value: AnalyticsSort; label: string }[] = [
    { value: '-last_viewed_at', label: 'Last viewed' },
    { value: '-created_at', label: 'Created' },
]

/** The person's own choices for every Analytics list, saved on their user. */
export function AnalyticsDisplayMenu(): JSX.Element {
    const { insightsHidden, defaultSort } = useValues(analyticsListLogic)
    const { setInsightsHidden, setDefaultSort } = useActions(analyticsListLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={<Button variant="outline" size="sm" className="h-8" data-attr="analytics-list-display" />}
            >
                Display
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-48">
                <DropdownMenuCheckboxItem
                    checked={insightsHidden}
                    closeOnClick={false}
                    onCheckedChange={(checked) => setInsightsHidden(checked)}
                    data-attr="analytics-list-hide-insights"
                >
                    Hide insights
                </DropdownMenuCheckboxItem>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                    <DropdownMenuLabel>Default sort</DropdownMenuLabel>
                    <DropdownMenuRadioGroup
                        value={defaultSort}
                        onValueChange={(value) => setDefaultSort(value as AnalyticsSort)}
                    >
                        {SORT_OPTIONS.map((option) => (
                            <DropdownMenuRadioItem
                                key={option.value}
                                value={option.value}
                                closeOnClick={false}
                                data-attr="analytics-list-default-sort"
                            >
                                {option.label}
                            </DropdownMenuRadioItem>
                        ))}
                    </DropdownMenuRadioGroup>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
