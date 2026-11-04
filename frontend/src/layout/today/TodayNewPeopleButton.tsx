import { router } from 'kea-router'

import { IconPlus } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

export function TodayNewPeopleButton(): JSX.Element {
    const customerAnalytics = useFeatureFlag('CUSTOMER_ANALYTICS')
    const journeys = useFeatureFlag('CUSTOMER_ANALYTICS_JOURNEYS')

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="icon"
                        className="-me-2 text-muted-foreground"
                        aria-label="New"
                        data-attr="today-new-people-header"
                    />
                }
            >
                <IconPlus />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => router.actions.push(urls.cohort('new'))} data-attr="people-new-cohort">
                    New cohort
                </DropdownMenuItem>
                {customerAnalytics && journeys && (
                    <DropdownMenuItem
                        onClick={() => router.actions.push(urls.customerJourneyTemplates())}
                        data-attr="people-new-journey"
                    >
                        New journey
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
