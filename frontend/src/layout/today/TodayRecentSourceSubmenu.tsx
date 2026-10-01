import { DropdownMenuCheckboxItem, DropdownMenuSeparator } from '@posthog/quill'

import { recentSourceLabel } from './todayRecentFilters'
import { TodayRecentFilterSubmenu } from './TodayRecentFilterSubmenu'

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
                    onCheckedChange={(checked) =>
                        onChange(checked ? [...selected, source] : selected.filter((kept) => kept !== source))
                    }
                    data-attr={dataAttr}
                >
                    {recentSourceLabel(source)}
                </DropdownMenuCheckboxItem>
            ))}
        </TodayRecentFilterSubmenu>
    )
}
