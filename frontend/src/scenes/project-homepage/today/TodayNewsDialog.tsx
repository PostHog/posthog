import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconTelescope } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    Text,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { TodayNewsBriefs } from './TodayNewsBriefs'
import { TodayNewsLead } from './TodayNewsLead'
import { todayNewsLogic } from './todayNewsLogic'
import { TodayNewsStoryRow } from './TodayNewsStoryRow'

export function TodayNewsDialog(): JSX.Element | null {
    const { isNewsOpen, edition } = useValues(todayNewsLogic)
    const { currentTeam } = useValues(teamLogic)
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
                    <span className="flex items-start justify-between gap-4 pr-8">
                        <span className="flex flex-col gap-1">
                            <span className="flex flex-wrap items-baseline gap-x-3">
                                <DialogTitle className="text-2xl tracking-tight">Today</DialogTitle>
                                <Text size="sm" variant="muted" render={<span />} translate="no">
                                    {today}
                                </Text>
                            </span>
                            <DialogDescription className="flex items-center gap-1.5">
                                <IconTelescope className="size-3.5 shrink-0" />
                                <span>
                                    Created by the Today scout from the last 24 hours of activity in{' '}
                                    {currentTeam?.name ?? 'your project'}.
                                </span>
                            </DialogDescription>
                        </span>
                        <Button
                            variant="outline"
                            size="sm"
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.inbox('scouts')} />}
                            onClick={closeNews}
                            data-attr="today-news-create-scout"
                        >
                            Create your own custom scout
                        </Button>
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
