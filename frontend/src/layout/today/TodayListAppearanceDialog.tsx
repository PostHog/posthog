import { useActions, useValues } from 'kea'

import {
    Autocomplete,
    AutocompleteList,
    Button,
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    ItemGroup,
    Text,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { listItemDetails } from './todayListAppearance'
import { TodayListAppearanceField } from './TodayListAppearanceField'
import { todayListAppearanceLogic } from './todayListAppearanceLogic'
import { TodaySessionStatusDot } from './TodaySessionStatusDot'
import { TodaySpacesRow } from './TodaySpacesRow'
import { activityDetail } from './todayWorkItems'

const PREVIEW_ROWS = [
    {
        title: 'Retry failed webhook deliveries',
        space: 'billing',
        repository: 'example-org/api',
        branch: 'fix/webhook-retries',
        creator: 'Ada Lovelace',
        hoursAgo: 2,
    },
    {
        title: 'Add a dark theme to settings',
        space: 'design',
        repository: 'example-org/web',
        branch: 'feat/settings-dark-theme',
        creator: 'Grace Hopper',
        hoursAgo: 3 * 24,
    },
    {
        title: 'Rewrite the SDK install guide',
        space: 'docs',
        repository: 'example-org/docs',
        branch: 'docs/sdk-install',
        creator: 'Katherine Johnson',
        hoursAgo: 3 * 7 * 24,
    },
]

const SETTLED_DOT = { mark: 'hollow', faint: false, label: 'Completed' } as const

export function TodayListAppearanceDialog(): JSX.Element {
    const { dialogOpen, draft, draftFields } = useValues(todayListAppearanceLogic)
    const { closeAppearanceDialog, toggleDraftField, moveDraftField, saveAppearance } =
        useActions(todayListAppearanceLogic)
    const now = dayjs()

    return (
        <Dialog open={dialogOpen} onOpenChange={(open: boolean) => !open && closeAppearanceDialog()}>
            <DialogContent showCloseButton={false} data-attr="today-list-appearance-dialog">
                <DialogHeader>
                    <DialogTitle>Edit list item appearance</DialogTitle>
                    <DialogDescription>
                        Add context under each session name to find related work faster.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody viewportClassName="flex flex-col gap-4">
                    <section aria-labelledby="today-list-appearance-preview" className="flex flex-col gap-2">
                        <Text id="today-list-appearance-preview" size="sm" weight="medium">
                            Preview
                        </Text>
                        {/* Real sidebar rows, so the preview shows the list as it looks. Inert, because nothing in it acts. */}
                        <div
                            className="pointer-events-none h-36 rounded-md border border-border bg-chrome p-1"
                            {...{ inert: '' }}
                        >
                            {/* Sidebar rows are autocomplete options, so the preview hosts them in an inline list. */}
                            <Autocomplete inline open>
                                <AutocompleteList className="!max-h-none !p-0">
                                    {PREVIEW_ROWS.map(({ title, hoursAgo, ...values }) => (
                                        <TodaySpacesRow
                                            key={title}
                                            optionValue={title}
                                            label={title}
                                            icon={<TodaySessionStatusDot dot={SETTLED_DOT} />}
                                            to={urls.ai()}
                                            active={false}
                                            dataAttr="today-list-appearance-preview-row"
                                            weight="regular"
                                            details={listItemDetails(
                                                {
                                                    ...values,
                                                    activity: activityDetail(
                                                        now.subtract(hoursAgo, 'hour').toISOString(),
                                                        now
                                                    ),
                                                },
                                                draftFields
                                            )}
                                        />
                                    ))}
                                </AutocompleteList>
                            </Autocomplete>
                        </div>
                    </section>
                    <section aria-labelledby="today-list-appearance-second-row" className="flex flex-col gap-2">
                        <div className="flex flex-col gap-1">
                            <Text id="today-list-appearance-second-row" size="sm" weight="medium">
                                Second row
                            </Text>
                            <Text size="xs" variant="muted">
                                Choose the details to show and move them into the order you want. Leave all unchecked
                                for a single-row list.
                            </Text>
                        </div>
                        <ItemGroup>
                            {draft.order.map((field, index) => (
                                <TodayListAppearanceField
                                    key={field}
                                    field={field}
                                    checked={draft.checked.includes(field)}
                                    first={index === 0}
                                    last={index === draft.order.length - 1}
                                    onCheckedChange={(checked) => toggleDraftField(field, checked)}
                                    onMove={(offset) => moveDraftField(field, offset)}
                                />
                            ))}
                        </ItemGroup>
                    </section>
                </DialogBody>
                <DialogFooter>
                    <DialogClose render={<Button variant="outline" data-attr="today-list-appearance-cancel" />}>
                        Cancel
                    </DialogClose>
                    <Button variant="primary" onClick={saveAppearance} data-attr="today-list-appearance-save">
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
