import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { Dialog, DialogBody, DialogContent, DialogHeader, DialogTitle, Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { TodayNewsEdition } from './TodayNewsEdition'
import { TodayNewsEditionSkeleton } from './TodayNewsEditionSkeleton'
import { todayNewsLogic } from './todayNewsLogic'
import { TodayNewsStatusNotice } from './TodayNewsStatusNotice'

export function TodayNewsDialog(): JSX.Element {
    const { isNewsOpen, edition, newsStatus } = useValues(todayNewsLogic)
    const { closeNews } = useActions(todayNewsLogic)
    const popupRef = useRef<HTMLDivElement>(null)

    const editionLine = edition
        ? [`${1 + edition.stories.length} new`, edition.ongoing.length > 0 ? `${edition.ongoing.length} ongoing` : null]
              .filter(Boolean)
              .join(' · ')
        : null

    return (
        <Dialog
            open={isNewsOpen}
            onOpenChange={(open) => {
                if (!open) {
                    closeNews()
                }
            }}
        >
            <DialogContent
                ref={popupRef}
                initialFocus={popupRef}
                size="wide"
                className="sm:max-w-4xl"
                data-attr="today-news-dialog"
            >
                <DialogHeader>
                    <span className="flex flex-wrap items-baseline gap-x-3 pe-8">
                        <DialogTitle className="text-2xl tracking-tight">Today</DialogTitle>
                        {edition ? (
                            <>
                                <Text size="sm" variant="muted" render={<span />} translate="no">
                                    {dayjs(edition.period_start).format('dddd, MMMM D')}
                                </Text>
                                <Text size="xs" variant="muted" render={<span />} className="ms-auto">
                                    {editionLine}
                                </Text>
                            </>
                        ) : null}
                    </span>
                </DialogHeader>
                <DialogBody viewportClassName="p-0">
                    <TodayNewsStatusNotice />
                    {edition ? (
                        <TodayNewsEdition edition={edition} />
                    ) : newsStatus === 'computing' ? (
                        <TodayNewsEditionSkeleton />
                    ) : null}
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
