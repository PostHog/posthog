import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { Dialog, DialogBody, DialogContent, DialogHeader, DialogTitle, Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { TodayNewsBriefs } from './TodayNewsBriefs'
import { TodayNewsLead } from './TodayNewsLead'
import { todayNewsLogic } from './todayNewsLogic'
import { TodayNewsStoryRow } from './TodayNewsStoryRow'

export function TodayNewsDialog(): JSX.Element | null {
    const { isNewsOpen, edition } = useValues(todayNewsLogic)
    const { closeNews, diveIn } = useActions(todayNewsLogic)
    const popupRef = useRef<HTMLDivElement>(null)
    const today = dayjs().format('dddd, MMMM D')

    if (!edition) {
        return null
    }

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
                    <span className="flex flex-wrap items-baseline gap-x-3 pr-8">
                        <DialogTitle className="text-2xl tracking-tight">Today</DialogTitle>
                        <Text size="sm" variant="muted" render={<span />} translate="no">
                            {today}
                        </Text>
                    </span>
                </DialogHeader>
                <DialogBody>
                    <div className="@container flex flex-col gap-8">
                        <TodayNewsLead story={edition.lead} onDiveIn={() => diveIn(edition.lead, 0)} />
                        <ul className="m-0 grid list-none gap-6 border-t p-0 pt-6 @3xl:grid-cols-3">
                            {edition.stories.map((story, index) => (
                                <TodayNewsStoryRow
                                    key={story.id}
                                    story={story}
                                    onDiveIn={() => diveIn(story, index + 1)}
                                />
                            ))}
                        </ul>
                        {edition.briefs.length > 0 ? <TodayNewsBriefs briefs={edition.briefs} /> : null}
                    </div>
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
