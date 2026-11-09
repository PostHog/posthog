import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { IconNewspaper } from '@posthog/icons'
import { Button } from '@posthog/quill'
import { PostHogErrorBoundary } from '@posthog/react'

import { lazyWithPreload } from 'lib/utils/retryImport'

import { todayNewsLogic } from './todayNewsLogic'

const TodayNewsDialog = lazyWithPreload(() => import('./TodayNewsDialog').then((m) => ({ default: m.TodayNewsDialog })))

export function TodayNewsButton(): JSX.Element | null {
    const { canOpenNews, showsNewsDialog, hasUnreadNews, newsStatus } = useValues(todayNewsLogic)
    const { openNews } = useActions(todayNewsLogic)

    if (!showsNewsDialog) {
        return null
    }

    const openButton = (onClick: () => void): JSX.Element | null =>
        canOpenNews ? (
            <Button
                variant="outline"
                className="rounded-full"
                indicator={hasUnreadNews ? 'default' : undefined}
                aria-label={
                    newsStatus === 'not_started'
                        ? "The news, today's edition is not written yet"
                        : hasUnreadNews
                          ? 'The news, with new stories since your last visit'
                          : 'The news'
                }
                onClick={onClick}
                data-attr="today-news-open"
            >
                <IconNewspaper />
                The news
            </Button>
        ) : null

    return (
        <PostHogErrorBoundary
            fallback={({ resetError }) =>
                openButton(() => {
                    resetError?.()
                    openNews()
                })
            }
        >
            {openButton(openNews)}
            <Suspense fallback={null}>
                <TodayNewsDialog.Component />
            </Suspense>
        </PostHogErrorBoundary>
    )
}
