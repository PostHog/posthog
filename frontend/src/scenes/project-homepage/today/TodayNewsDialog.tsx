import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconTelescope } from '@posthog/icons'
import {
    Button,
    CardGroup,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
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
                    <DialogTitle className="text-2xl tracking-tight">Today</DialogTitle>
                    <DialogDescription className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                        <span>{currentTeam?.name ?? 'Your project'}</span>
                        <span aria-hidden>·</span>
                        <span translate="no">{today}</span>
                        <span aria-hidden>·</span>
                        <IconTelescope className="size-3.5 shrink-0" />
                        <span>Edited by a scout.</span>
                        <Button
                            variant="link"
                            size="inline"
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.inbox('scouts')} />}
                            onClick={closeNews}
                            data-attr="today-news-create-scout"
                        >
                            Hire your own
                        </Button>
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <div className="@container flex flex-col gap-4">
                        <div className="grid gap-4 @3xl:grid-cols-5">
                            <div className="@3xl:col-span-3">
                                <TodayNewsLead story={edition.lead} onDiveIn={() => diveIn(edition.lead, 0)} />
                            </div>
                            <CardGroup className="flex flex-col self-start @3xl:col-span-2">
                                {edition.stories.map((story, index) => (
                                    <TodayNewsStoryRow
                                        key={story.id}
                                        story={story}
                                        onDiveIn={() => diveIn(story, index + 1)}
                                    />
                                ))}
                            </CardGroup>
                        </div>
                        {edition.briefs.length > 0 ? <TodayNewsBriefs briefs={edition.briefs} /> : null}
                    </div>
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
