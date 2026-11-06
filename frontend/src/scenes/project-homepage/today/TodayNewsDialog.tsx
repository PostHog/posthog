import { useActions, useValues } from 'kea'

import {
    Badge,
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { TodayNewsLead } from './TodayNewsLead'
import { todayNewsLogic } from './todayNewsLogic'
import { TodayNewsStoryRow } from './TodayNewsStoryRow'

export function TodayNewsDialog(): JSX.Element {
    const { isNewsOpen, edition } = useValues(todayNewsLogic)
    const { closeNews, diveIn } = useActions(todayNewsLogic)

    return (
        <Dialog
            open={isNewsOpen}
            onOpenChange={(open) => {
                if (!open) {
                    closeNews()
                }
            }}
        >
            <DialogContent size="wide" data-attr="today-news-dialog">
                <DialogHeader>
                    <span className="flex items-center gap-2">
                        <DialogTitle>This week in your project</DialogTitle>
                        {edition.isSample ? <Badge>Sample</Badge> : null}
                    </span>
                    <DialogDescription>
                        Important changes across the whole project, including work you are not part of.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <div className="@container">
                        <div className="grid gap-8 @3xl:grid-cols-2">
                            <TodayNewsLead story={edition.lead} onDiveIn={() => diveIn(edition.lead, 0)} />
                            <div className="flex flex-col">
                                {edition.stories.map((story, index) => (
                                    <TodayNewsStoryRow
                                        key={story.id}
                                        story={story}
                                        onDiveIn={() => diveIn(story, index + 1)}
                                    />
                                ))}
                                {edition.briefs.length > 0 ? (
                                    <section className="flex flex-col gap-1 border-t pt-4">
                                        <Text size="sm" variant="muted">
                                            Also this week
                                        </Text>
                                        <ul className="m-0 flex list-none flex-col gap-1 p-0">
                                            {edition.briefs.map((brief) => (
                                                <li key={brief}>
                                                    <Text size="sm">{brief}</Text>
                                                </li>
                                            ))}
                                        </ul>
                                    </section>
                                ) : null}
                            </div>
                        </div>
                    </div>
                </DialogBody>
                <DialogFooter className="sm:items-center sm:justify-between">
                    <Text size="sm" variant="muted">
                        {edition.isSample
                            ? 'A scout will write this news every day from what changed in the project.'
                            : 'A scout wrote this news from what changed in the project.'}
                    </Text>
                    <Button
                        variant="link"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.inbox('scouts')} />}
                        onClick={closeNews}
                        data-attr="today-news-create-scout"
                    >
                        Create your own scout
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
