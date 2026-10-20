import { IconWarning } from '@posthog/icons'
import {
    Button,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { MathChoice, MathSelectorChoices, isMathChoiceGroup } from './useMathSelectorChoices'

interface QuillMathMenuItemsProps {
    choices: MathSelectorChoices
    value: string
    onChange: (value: string) => void
    disabled?: boolean
}

function MathChoiceItem({
    choice,
    useShortLabel,
    disabled,
}: {
    choice: MathChoice
    useShortLabel?: boolean
    disabled?: boolean
}): JSX.Element {
    const help = choice.disabledReason ?? choice.warning ?? choice.description
    const item = (
        <DropdownMenuRadioItem
            value={choice.value}
            disabled={disabled || !!choice.disabledReason}
            data-attr={choice.dataAttr}
        >
            {choice.warning ? <IconWarning className="text-warning-foreground" /> : null}
            {useShortLabel ? (choice.shortLabel ?? choice.label) : choice.label}
        </DropdownMenuRadioItem>
    )
    if (!help) {
        return item
    }
    return (
        <Tooltip>
            <TooltipTrigger render={item} />
            <TooltipContent side="right" className="max-w-80">
                {help}
            </TooltipContent>
        </Tooltip>
    )
}

/** The math types of a series as quill menu items, with each family of sub-choices in a submenu. */
export function QuillMathMenuItems({ choices, value, onChange, disabled }: QuillMathMenuItemsProps): JSX.Element {
    return (
        <>
            <DropdownMenuRadioGroup value={value} onValueChange={(newValue) => onChange(newValue as string)}>
                {choices.entries.map((entry) =>
                    isMathChoiceGroup(entry) ? (
                        <DropdownMenuSub key={entry.dataAttr}>
                            <DropdownMenuSubTrigger data-attr={entry.dataAttr} disabled={disabled}>
                                {entry.label}
                                {entry.choices.some((choice) => choice.value === value) ? (
                                    <Text size="xs" variant="muted" render={<span />} className="ms-auto">
                                        {entry.choices.find((choice) => choice.value === value)?.shortLabel}
                                    </Text>
                                ) : null}
                            </DropdownMenuSubTrigger>
                            <DropdownMenuSubContent>
                                <DropdownMenuRadioGroup
                                    value={value}
                                    onValueChange={(newValue) => onChange(newValue as string)}
                                >
                                    {entry.choices.map((choice) => (
                                        <MathChoiceItem
                                            key={choice.value}
                                            choice={choice}
                                            useShortLabel
                                            disabled={disabled}
                                        />
                                    ))}
                                </DropdownMenuRadioGroup>
                            </DropdownMenuSubContent>
                        </DropdownMenuSub>
                    ) : (
                        <MathChoiceItem key={entry.value} choice={entry} disabled={disabled} />
                    )
                )}
            </DropdownMenuRadioGroup>
            {choices.groupsIntroduction ? (
                <>
                    <DropdownMenuSeparator />
                    <Text size="xs" variant="muted" render={<p />} className="m-0 max-w-60 px-2 py-1">
                        {choices.groupsIntroduction.needsUpgrade ? (
                            <>
                                Track usage of groups of users with Group Analytics.{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={<LinkPrimitive to="/organization/billing" target="_blank" />}
                                    data-attr="group-analytics-upgrade"
                                >
                                    Upgrade now
                                </Button>{' '}
                                or{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={
                                        <LinkPrimitive
                                            to="https://posthog.com/docs/user-guides/group-analytics?utm_medium=in-product&utm_campaign=group-analytics-learn-more"
                                            target="_blank"
                                        />
                                    }
                                    data-attr="group-analytics-learn-more"
                                >
                                    learn more
                                </Button>
                                .
                            </>
                        ) : (
                            <>
                                You can now use Group Analytics. See{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={
                                        <LinkPrimitive
                                            to="https://posthog.com/docs/product-analytics/group-analytics?utm_medium=in-product&utm_campaign=group-analytics-get-started"
                                            target="_blank"
                                        />
                                    }
                                    data-attr="group-analytics-get-started"
                                >
                                    how to get started
                                </Button>
                                .
                            </>
                        )}
                    </Text>
                </>
            ) : null}
        </>
    )
}
