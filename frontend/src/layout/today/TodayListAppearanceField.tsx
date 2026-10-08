import { IconChevronDown, IconClock, IconGitBranch, IconGitRepository, IconPerson } from '@posthog/icons'
import {
    Button,
    Checkbox,
    Field,
    Item,
    ItemActions,
    ItemContent,
    Label,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { TODAY_LIST_ITEM_FIELD_LABELS, TodayListItemField } from './todayListAppearance'
import { TodaySpaceGlyph } from './TodaySpaceGlyph'

const FIELD_ICONS: Record<TodayListItemField, JSX.Element> = {
    space: <TodaySpaceGlyph locked={false} />,
    repository: <IconGitRepository />,
    branch: <IconGitBranch />,
    creator: <IconPerson />,
    activity: <IconClock />,
}

interface TodayListAppearanceFieldProps {
    field: TodayListItemField
    checked: boolean
    first: boolean
    last: boolean
    onCheckedChange: (checked: boolean) => void
    onMove: (offset: -1 | 1) => void
}

/** One detail in the appearance dialog. Desktop drags to reorder; here, up and down buttons do it from the keyboard too. */
export function TodayListAppearanceField({
    field,
    checked,
    first,
    last,
    onCheckedChange,
    onMove,
}: TodayListAppearanceFieldProps): JSX.Element {
    const label = TODAY_LIST_ITEM_FIELD_LABELS[field]
    const checkboxId = `today-list-appearance-${field}`
    const moves: { offset: -1 | 1; text: string; disabled: boolean }[] = [
        { offset: -1, text: `Move ${label} up`, disabled: first },
        { offset: 1, text: `Move ${label} down`, disabled: last },
    ]
    return (
        <Item variant="outline" size="xs">
            <ItemContent>
                <Field orientation="horizontal">
                    <Checkbox
                        id={checkboxId}
                        checked={checked}
                        onCheckedChange={(value: boolean) => onCheckedChange(value)}
                        data-attr={`today-list-appearance-field-${field}`}
                    />
                    <Label htmlFor={checkboxId} className="flex cursor-pointer items-center gap-2">
                        <span className="flex size-4 items-center justify-center text-muted-foreground">
                            {FIELD_ICONS[field]}
                        </span>
                        {label}
                    </Label>
                </Field>
            </ItemContent>
            <ItemActions>
                {moves.map(({ offset, text, disabled }) => (
                    <Tooltip key={offset}>
                        <TooltipTrigger
                            delay={0}
                            render={
                                <Button
                                    size="icon-xs"
                                    aria-label={text}
                                    disabled={disabled}
                                    onClick={() => onMove(offset)}
                                    data-attr={`today-list-appearance-move-${offset < 0 ? 'up' : 'down'}`}
                                />
                            }
                        >
                            <IconChevronDown className={offset < 0 ? 'rotate-180' : undefined} />
                        </TooltipTrigger>
                        <TooltipContent>{text}</TooltipContent>
                    </Tooltip>
                ))}
            </ItemActions>
        </Item>
    )
}
