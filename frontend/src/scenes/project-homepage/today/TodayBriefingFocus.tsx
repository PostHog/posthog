import { useActions, useValues } from 'kea'

import { IconTarget } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Item,
    ItemActions,
    ItemContent,
    ItemGroup,
    ItemTitle,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { TodayFocusDirection, TodayFocusDuration } from './todayBriefingFocus'
import { todayBriefingFocusLogic } from './todayBriefingFocusLogic'

const PRESSED = 'data-[pressed]:border-primary data-[pressed]:bg-primary/10 data-[pressed]:text-primary'

const DURATIONS: { value: TodayFocusDuration; label: string }[] = [
    { value: 'week', label: 'For this week' },
    { value: 'always', label: 'Until I change it' },
]

export function TodayBriefingFocusButton(): JSX.Element {
    const { hasCurrentFocus } = useValues(todayBriefingFocusLogic)
    const { openFocusDialog } = useActions(todayBriefingFocusLogic)
    return (
        <Button
            variant="outline"
            size="xs"
            onClick={openFocusDialog}
            aria-pressed={hasCurrentFocus}
            data-attr="today-briefing-focus-open"
        >
            <IconTarget />
            Focus
        </Button>
    )
}

/** The focus the briefing follows, under the greeting, so the person sees why the list looks the way it does. */
export function TodayBriefingFocusLine(): JSX.Element | null {
    const { hasCurrentFocus, currentFocusSummary } = useValues(todayBriefingFocusLogic)
    const { openFocusDialog, clearFocus } = useActions(todayBriefingFocusLogic)
    if (!hasCurrentFocus) {
        return null
    }
    return (
        <p className="TodayHome__focus" data-attr="today-briefing-focus-line">
            <span>{`${currentFocusSummary}. `}</span>
            <button type="button" onClick={openFocusDialog} data-attr="today-briefing-focus-edit">
                Edit
            </button>
            <span> · </span>
            <button type="button" onClick={clearFocus} data-attr="today-briefing-focus-clear">
                Clear
            </button>
        </p>
    )
}

export function TodayBriefingFocusDialog(): JSX.Element {
    const { focusDialogOpen, draft, draftTopics } = useValues(todayBriefingFocusLogic)
    const { closeFocusDialog, setDraftTopic, setDraftDuration, saveFocus } = useActions(todayBriefingFocusLogic)

    return (
        <Dialog open={focusDialogOpen} onOpenChange={(open: boolean) => !open && closeFocusDialog()}>
            <DialogContent showCloseButton={false} data-attr="today-briefing-focus-dialog">
                <DialogHeader>
                    <DialogTitle>Focus your briefing</DialogTitle>
                    <DialogDescription>
                        Choose what your briefing shows more or less of. Reports that wait for your input and P0 reports
                        always stay in it.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody viewportClassName="flex flex-col gap-4">
                    <section aria-labelledby="today-briefing-focus-topics" className="flex flex-col gap-2">
                        <Text id="today-briefing-focus-topics" size="sm" weight="medium">
                            Topics
                        </Text>
                        <ItemGroup>
                            {draftTopics.map((topic) => (
                                <Item key={topic.key} size="sm">
                                    <ItemContent>
                                        <ItemTitle>{topic.label}</ItemTitle>
                                    </ItemContent>
                                    <ItemActions>
                                        <ToggleGroup
                                            size="sm"
                                            spacing={1}
                                            aria-label={`More or less ${topic.label}`}
                                            value={draft.topics[topic.key] ? [draft.topics[topic.key]] : []}
                                            onValueChange={(value: string[]) =>
                                                setDraftTopic(topic.key, (value[0] as TodayFocusDirection) ?? null)
                                            }
                                        >
                                            <ToggleGroupItem
                                                value="less"
                                                className={PRESSED}
                                                data-attr="today-briefing-focus-less"
                                            >
                                                Less
                                            </ToggleGroupItem>
                                            <ToggleGroupItem
                                                value="more"
                                                className={PRESSED}
                                                data-attr="today-briefing-focus-more"
                                            >
                                                More
                                            </ToggleGroupItem>
                                        </ToggleGroup>
                                    </ItemActions>
                                </Item>
                            ))}
                        </ItemGroup>
                    </section>
                    <section aria-labelledby="today-briefing-focus-duration" className="flex flex-col gap-2">
                        <Text id="today-briefing-focus-duration" size="sm" weight="medium">
                            Keep this focus
                        </Text>
                        <ToggleGroup
                            size="sm"
                            spacing={1}
                            aria-labelledby="today-briefing-focus-duration"
                            value={[draft.duration]}
                            // A single toggle group lets the pressed item go; the duration always has a value.
                            onValueChange={(value: string[]) =>
                                value[0] && setDraftDuration(value[0] as TodayFocusDuration)
                            }
                        >
                            {DURATIONS.map(({ value, label }) => (
                                <ToggleGroupItem key={value} value={value} className={PRESSED}>
                                    {label}
                                </ToggleGroupItem>
                            ))}
                        </ToggleGroup>
                    </section>
                </DialogBody>
                <DialogFooter>
                    <DialogClose render={<Button variant="outline" data-attr="today-briefing-focus-cancel" />}>
                        Cancel
                    </DialogClose>
                    <Button variant="primary" onClick={saveFocus} data-attr="today-briefing-focus-save">
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
