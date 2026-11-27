import { Checkbox, Field, FieldContent, FieldDescription, FieldLabel, FieldTitle } from '@posthog/quill'

import { TODAY_PANE_INTROS } from './todayPaneIntros'
import { TODAY_PANES } from './todayRailItems'
import type { TodayRailPane } from './todayShellLogic'

/** A pane the person shows or hides, or one that keeps its place, with the reason it does. */
type TodayRailPaneCheckboxProps =
    | { pane: TodayRailPane; checked: boolean; onToggle: () => void }
    | { pane: TodayRailPane; lockedReason: string }

/** A rail pane's checkbox, name and intro, labelled as one control so the text toggles it too. */
export function TodayRailPaneCheckbox(props: TodayRailPaneCheckboxProps): JSX.Element {
    const { pane } = props
    const locked = 'lockedReason' in props
    return (
        <FieldLabel
            disabledReason={locked ? props.lockedReason : undefined}
            className="min-w-0 flex-1 border-0 bg-transparent p-0"
        >
            <Field orientation="horizontal">
                <Checkbox
                    // A locked pane is always on the rail.
                    checked={locked || props.checked}
                    onCheckedChange={locked ? undefined : props.onToggle}
                    data-attr={`today-rail-customize-${pane}`}
                />
                <FieldContent>
                    <FieldTitle className="flex items-center gap-2 [&_svg]:size-4">
                        {TODAY_PANES[pane].icon}
                        {TODAY_PANES[pane].label}
                    </FieldTitle>
                    <FieldDescription>{TODAY_PANE_INTROS[pane].description}</FieldDescription>
                </FieldContent>
            </Field>
        </FieldLabel>
    )
}
