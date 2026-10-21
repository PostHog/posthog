import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

export interface TodayMenuLinkItemOptions {
    external?: boolean
    /** Loads the page fresh, for routes outside the app router such as Django admin. */
    disableClientSideRouting?: boolean
}

export function todayMenuLinkItem(to: string, options: TodayMenuLinkItemOptions = {}): JSX.Element {
    return (
        <Button
            size="row"
            left
            render={
                <LinkPrimitive
                    to={to}
                    target={options.external ? '_blank' : undefined}
                    disableClientSideRouting={options.disableClientSideRouting}
                />
            }
        />
    )
}
