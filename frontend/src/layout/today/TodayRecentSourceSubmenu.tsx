import { DropdownMenuCheckboxItem, DropdownMenuSeparator, ItemCheckbox } from '@posthog/quill'

import { recentSourceLabel } from './todayRecentFilters'
import { TodayRecentFilterSubmenu } from './TodayRecentFilterSubmenu'
import { useTodaySheetMenu } from './todaySheetMenuContext'

interface TodayRecentSourceSubmenuProps {
    /** The sources kept. An empty list keeps every source. */
    selected: string[]
    options: string[]
    onChange: (sources: string[]) => void
    /** The option rows' `data-attr`. The "Any source" row adds `-any`. */
    dataAttr: string
}

function sourcesLabel(sources: string[]): string {
    if (!sources.length) {
        return 'Any source'
    }
    return sources.length > 2 ? `${sources.length} sources` : sources.map(recentSourceLabel).join(', ')
}

export function TodayRecentSourceSubmenu({
    selected,
    options,
    onChange,
    dataAttr,
}: TodayRecentSourceSubmenuProps): JSX.Element {
    const sheet = useTodaySheetMenu()
    const toggle = (source: string, checked: boolean): void =>
        onChange(checked ? [...selected, source] : selected.filter((kept) => kept !== source))
    if (sheet) {
        return (
            <TodayRecentFilterSubmenu label="Source" value={sourcesLabel(selected)} narrowed={selected.length > 0}>
                <ItemCheckbox
                    className="text-base"
                    aria-checked={!selected.length}
                    onClick={() => onChange([])}
                    data-attr={`${dataAttr}-any`}
                >
                    Any source
                </ItemCheckbox>
                <div role="separator" className="my-1 border-t border-border" />
                {options.map((source) => (
                    <ItemCheckbox
                        key={source}
                        className="text-base"
                        aria-checked={selected.includes(source)}
                        onClick={() => toggle(source, !selected.includes(source))}
                        data-attr={dataAttr}
                    >
                        {recentSourceLabel(source)}
                    </ItemCheckbox>
                ))}
            </TodayRecentFilterSubmenu>
        )
    }
    return (
        <TodayRecentFilterSubmenu label="Source" value={sourcesLabel(selected)} narrowed={selected.length > 0}>
            <DropdownMenuCheckboxItem
                checked={!selected.length}
                closeOnClick={false}
                onCheckedChange={() => onChange([])}
                data-attr={`${dataAttr}-any`}
            >
                Any source
            </DropdownMenuCheckboxItem>
            <DropdownMenuSeparator />
            {options.map((source) => (
                <DropdownMenuCheckboxItem
                    key={source}
                    checked={selected.includes(source)}
                    closeOnClick={false}
                    onCheckedChange={(checked) => toggle(source, checked)}
                    data-attr={dataAttr}
                >
                    {recentSourceLabel(source)}
                </DropdownMenuCheckboxItem>
            ))}
        </TodayRecentFilterSubmenu>
    )
}
