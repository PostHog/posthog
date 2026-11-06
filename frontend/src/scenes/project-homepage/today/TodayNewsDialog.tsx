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
    const weekStart = dayjs()
        .subtract((dayjs().day() + 6) % 7, 'day')
        .format('MMM D')

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
                                This week
                            </DialogTitle>
                            <DialogDescription className="flex flex-wrap items-baseline justify-between gap-x-4 font-mono text-xs tracking-wide uppercase">
                                <span>{currentTeam?.name ?? 'Your project'}</span>
                                <span translate="no">
                                    {edition.isSample ? 'Sample edition · ' : ''}Week of {weekStart}
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
                        <p className="m-0 flex flex-wrap items-center gap-x-2 border-t pt-3 font-mono text-xs tracking-wide text-muted-foreground uppercase">
                            <span className="text-foreground [&_svg]:size-3.5">
                                <IconTelescope />
                            </span>
                            <span>{edition.isSample ? 'A scout will edit this news' : 'Edited by a scout'}</span>
                            <span aria-hidden>·</span>
                            <Button
                                variant="link-foreground"
                                size="inline"
                                nativeButton={false}
                                render={<LinkPrimitive to={urls.inbox('scouts')} />}
                                onClick={closeNews}
                                data-attr="today-news-create-scout"
                            >
                                Create your own scout
                            </Button>
                        </p>
                    </div>
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
