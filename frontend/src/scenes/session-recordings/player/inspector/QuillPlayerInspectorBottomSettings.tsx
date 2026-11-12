import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { miniFiltersLogic } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { QuillInspectorToggle } from './components/QuillInspectorToggle'
import { playerInspectorLogic } from './playerInspectorLogic'

export function QuillPlayerInspectorBottomSettings(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const inspectorLogic = playerInspectorLogic(logicProps)
    const { syncScrollPaused, hasEventsToDisplay, allowMatchingEventsFilter } = useValues(inspectorLogic)
    const { setSyncScrollPaused } = useActions(inspectorLogic)
    const { showOnlyMatching, showLineTooltips, hasEventsFiltersSelected } = useValues(miniFiltersLogic)
    const { setShowOnlyMatching, setShowLineTooltips } = useActions(miniFiltersLogic)
    const { hideNullValues, hidePostHogPropertiesInTable } = useValues(userPreferencesLogic)
    const { setHideNullValues, setHidePostHogPropertiesInTable } = useActions(userPreferencesLogic)

    const noEventsReason =
        hasEventsToDisplay && hasEventsFiltersSelected ? undefined : 'There are no events in the list'

    return (
        <div
            data-quill
            className="flex flex-wrap items-center gap-0.5 px-2 py-1 border-t border-border text-foreground"
        >
            <QuillInspectorToggle
                pressed={!syncScrollPaused}
                onPressedChange={(pressed) => setSyncScrollPaused(!pressed)}
                tooltip={
                    syncScrollPaused
                        ? 'Scroll the activity list in sync with playback'
                        : 'Do not auto-scroll the activity list in sync with playback'
                }
                data-attr="inspector-sync-scrolling"
            >
                Sync
            </QuillInspectorToggle>
            <QuillInspectorToggle
                pressed={hasEventsToDisplay && showOnlyMatching && allowMatchingEventsFilter}
                onPressedChange={() => setShowOnlyMatching(!showOnlyMatching)}
                tooltip={
                    showOnlyMatching
                        ? 'Show all events for this recording'
                        : 'Show only events that match the current filters'
                }
                disabledReason={
                    noEventsReason ??
                    (allowMatchingEventsFilter ? undefined : 'There are no event filters to match against')
                }
                data-attr="inspector-show-only-matching"
            >
                Matching only
            </QuillInspectorToggle>
            <QuillInspectorToggle
                pressed={showLineTooltips}
                onPressedChange={setShowLineTooltips}
                tooltip={
                    showLineTooltips ? 'Hide hover tooltips on inspector lines' : 'Show the full line content on hover'
                }
                data-attr="inspector-line-tooltips"
            >
                Tooltips
            </QuillInspectorToggle>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            size="sm"
                            className="text-muted-foreground"
                            data-attr="inspector-hide-properties-menu"
                        />
                    }
                >
                    Properties
                    <IconChevronDown />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    <DropdownMenuCheckboxItem
                        checked={hidePostHogPropertiesInTable}
                        onCheckedChange={setHidePostHogPropertiesInTable}
                        disabledReason={noEventsReason}
                        closeOnClick={false}
                        data-attr="inspector-hide-posthog-properties"
                    >
                        Hide PostHog properties
                    </DropdownMenuCheckboxItem>
                    <DropdownMenuCheckboxItem
                        checked={hideNullValues}
                        onCheckedChange={setHideNullValues}
                        disabledReason={noEventsReason}
                        closeOnClick={false}
                        data-attr="inspector-hide-null-values"
                    >
                        Hide null values
                    </DropdownMenuCheckboxItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}
