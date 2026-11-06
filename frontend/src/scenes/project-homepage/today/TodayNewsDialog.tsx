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
                    <DialogTitle className="text-2xl tracking-tight">Today</DialogTitle>
                    <DialogDescription>
                        {currentTeam?.name ?? 'Your project'} · <span translate="no">{today}</span>
                    </DialogDescription>
                    <Text
                        size="xs"
                        variant="muted"
                        render={<p />}
                        className="m-0 flex flex-wrap items-center gap-x-1.5"
                    >
                        <IconTelescope className="size-3.5 shrink-0" />
                        <span>Created by the Today scout from the last 24 hours of project activity.</span>
                        <Button
                            variant="link"
                            size="inline"
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.inbox('scouts')} />}
                            onClick={closeNews}
                            data-attr="today-news-create-scout"
                        >
                            Create your own custom scout
                        </Button>
                    </Text>
                </DialogHeader>
                <DialogBody>
                    <div className="@container flex flex-col gap-6">
                        <div className="grid gap-6 @3xl:grid-cols-5 @3xl:gap-8">
                            <div className="@3xl:col-span-3">
                                <TodayNewsLead story={edition.lead} onDiveIn={() => diveIn(edition.lead, 0)} />
                            </div>
                            <ul className="m-0 flex list-none flex-col p-0 @3xl:col-span-2">
                                {edition.stories.map((story, index) => (
                                    <TodayNewsStoryRow
                                        key={story.id}
                                        story={story}
                                        onDiveIn={() => diveIn(story, index + 1)}
                                    />
                                ))}
                            </ul>
                        </div>
                        {edition.briefs.length > 0 ? <TodayNewsBriefs briefs={edition.briefs} /> : null}
                    </div>
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
