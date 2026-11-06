import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconTelescope } from '@posthog/icons'
import { Button, Dialog, DialogBody, DialogContent, DialogDescription, DialogTitle } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { TodayNewsBriefs } from './TodayNewsBriefs'
import { TodayNewsLead } from './TodayNewsLead'
import { todayNewsLogic } from './todayNewsLogic'
import { TodayNewsStoryRow } from './TodayNewsStoryRow'

export function TodayNewsDialog(): JSX.Element {
    const { isNewsOpen, edition } = useValues(todayNewsLogic)
    const { currentTeam } = useValues(teamLogic)
    const { closeNews, diveIn } = useActions(todayNewsLogic)
    const popupRef = useRef<HTMLDivElement>(null)
    const today = dayjs().format('dddd, MMMM D')

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
                <DialogBody>
                    <div className="@container flex flex-col gap-6 px-2 pt-2 pb-1">
                        <header className="flex flex-col gap-2 border-b-4 border-double border-foreground pb-2">
                            <DialogTitle className="m-0 text-center text-[3.5rem] leading-none font-bold tracking-tighter">
                                Today
                            </DialogTitle>
                            <DialogDescription className="grid grid-cols-1 gap-x-4 gap-y-1 font-mono text-xs tracking-wide uppercase @2xl:grid-cols-[1fr_auto_1fr]">
                                <span className="truncate">{currentTeam?.name ?? 'Your project'}</span>
                                <span className="flex items-center gap-1.5 @2xl:justify-center">
                                    <IconTelescope className="size-3.5 shrink-0 text-foreground" />
                                    <span>Editor in chief: a scout</span>
                                    <span aria-hidden>·</span>
                                    <Button
                                        variant="link-foreground"
                                        size="inline"
                                        nativeButton={false}
                                        render={<LinkPrimitive to={urls.inbox('scouts')} />}
                                        onClick={closeNews}
                                        data-attr="today-news-create-scout"
                                    >
                                        Hire your own
                                    </Button>
                                </span>
                                <span translate="no" className="@2xl:text-right">
                                    {today}
                                </span>
                            </DialogDescription>
                        </header>
                        <div className="grid gap-6 @3xl:grid-cols-[5fr_3fr]">
                            <TodayNewsLead story={edition.lead} onDiveIn={() => diveIn(edition.lead, 0)} />
                            <ul className="m-0 flex list-none flex-col p-0 @3xl:border-l @3xl:pl-6">
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
