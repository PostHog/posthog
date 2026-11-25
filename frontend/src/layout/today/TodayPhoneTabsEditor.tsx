import { useActions, useValues } from 'kea'

import { ItemCheckbox, ItemMenuItem, ItemSeparator } from '@posthog/quill'

import { TODAY_PHONE_TAB_LIMIT } from './todayPhoneTabs'
import { todayPhoneTabsLogic } from './todayPhoneTabsLogic'
import { TODAY_PANES } from './todayRailItems'
import { todayShellLogic } from './todayShellLogic'

export function TodayPhoneTabsEditor(): JSX.Element {
    const { railPanes } = useValues(todayShellLogic)
    const { phoneTabPanes, phoneTabChoice } = useValues(todayPhoneTabsLogic)
    const { togglePhoneTab, resetPhoneTabs } = useActions(todayPhoneTabsLogic)
    const full = phoneTabPanes.length >= TODAY_PHONE_TAB_LIMIT

    return (
        <>
            <p className="m-0 px-2 pb-2 text-sm text-muted-foreground">
                Choose up to {TODAY_PHONE_TAB_LIMIT} areas for the tab bar. Search and More stay in the bar.
            </p>
            {railPanes.map((pane) => {
                const checked = phoneTabPanes.includes(pane)
                return (
                    <ItemCheckbox
                        key={pane}
                        className="text-base disabled:opacity-50"
                        aria-checked={checked}
                        disabled={checked ? phoneTabPanes.length === 1 : full}
                        onClick={() => togglePhoneTab(pane)}
                        data-attr={`today-phone-tab-${pane}`}
                    >
                        <span className="flex items-center gap-2 [&_svg]:size-4">
                            {TODAY_PANES[pane].icon}
                            {TODAY_PANES[pane].label}
                        </span>
                    </ItemCheckbox>
                )
            })}
            {phoneTabChoice !== null && (
                <>
                    <ItemSeparator className="my-1" />
                    <ItemMenuItem className="text-base" onClick={resetPhoneTabs} data-attr="today-phone-tabs-reset">
                        Reset to default tabs
                    </ItemMenuItem>
                </>
            )}
        </>
    )
}
