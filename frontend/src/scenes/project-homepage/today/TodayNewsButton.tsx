import { useActions, useValues } from 'kea'

import { IconNewspaper } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { todayNewsLogic } from './todayNewsLogic'

export function TodayNewsButton(): JSX.Element {
    const { hasUnreadNews } = useValues(todayNewsLogic)
    const { openNews } = useActions(todayNewsLogic)

    return (
        <Button
            variant="outline"
            className="rounded-full"
            indicator={hasUnreadNews ? 'default' : undefined}
            aria-label={hasUnreadNews ? 'The news, with new stories since your last visit' : 'The news'}
            onClick={openNews}
            data-attr="today-news-open"
        >
            <IconNewspaper />
            The news
        </Button>
    )
}
