import { useActions } from 'kea'

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    ItemContent,
    ItemDescription,
    ItemTitle,
} from '@posthog/quill'

import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'
import { ANALYTICS_TYPES } from './analyticsUtils'
import { NewAnalyticsSource, newAnalyticsLogic } from './newAnalyticsLogic'

interface NewAnalyticsMenuProps {
    /** The element that opens the menu, such as a quill `Button`. The menu merges its own props onto it. */
    trigger: JSX.Element
    source: NewAnalyticsSource
    children?: React.ReactNode
}

/** Asks which type of analytics to create, then hands off to that type's own create flow. */
export function NewAnalyticsMenu({ trigger, source, children }: NewAnalyticsMenuProps): JSX.Element {
    const { pickNewAnalyticsType } = useActions(newAnalyticsLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={trigger}>{children}</DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-72">
                {ANALYTICS_TYPES.map((info) => (
                    <DropdownMenuItem
                        key={info.type}
                        className="h-auto cursor-pointer items-start py-1.5 whitespace-normal [&>svg]:mt-1.5"
                        onClick={() => pickNewAnalyticsType(info.type, source)}
                        data-attr={`analytics-new-${info.type}`}
                    >
                        <AnalyticsTypeIcon type={info.type} />
                        <ItemContent variant="menuItem">
                            <ItemTitle>{info.label}</ItemTitle>
                            <ItemDescription>{info.description}</ItemDescription>
                        </ItemContent>
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
