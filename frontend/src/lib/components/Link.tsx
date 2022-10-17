import { router } from 'kea-router'
import { isExternalLink } from 'lib/utils'

type RoutePart = string | Record<string, any>

export type LinkProps = Pick<
    React.HTMLProps<HTMLAnchorElement>,
    'target' | 'className' | 'onClick' | 'children' | 'title'
> & {
    /** The location to go to. This can be a kea-location or a "href"-like string */
    to?: string | [string, RoutePart?, RoutePart?]
    /** If true, in-app navigation will not be used and the link will navigate with a page load */
    disableClientSideRouting?: boolean
    preventClick?: boolean
}

// Some URLs we want to enforce a full reload such as billing which is redirected by Django
const FORCE_PAGE_LOAD = ['/billing/']

const shouldForcePageLoad = (input: any): boolean => {
    if (!input || typeof input !== 'string') {
        return false
    }
    return !!FORCE_PAGE_LOAD.find((x) => input.startsWith(x))
}

/**
 * Link
 *
 * This component wraps an <a> element to ensure that proper tags are added related to target="_blank"
 * as well deciding when a given "to" link should be opened as a standard navigation (i.e. a standard href)
 * or whether to be routed internally via kea-router
 */
export function Link({ to, target, disableClientSideRouting, preventClick = false, ...props }: LinkProps): JSX.Element {
    const onClick = (event: React.MouseEvent<HTMLAnchorElement>): void => {
        if (event.metaKey || event.ctrlKey) {
            event.stopPropagation()
            return
        }

        if (!target && to && !isExternalLink(to) && !disableClientSideRouting && !shouldForcePageLoad(to)) {
            event.preventDefault()
            if (to && to !== '#' && !preventClick) {
                if (Array.isArray(to)) {
                    router.actions.push(...to)
                } else {
                    router.actions.push(to)
                }
            }
        }
        props.onClick?.(event)
    }

    return (
        // eslint-disable-next-line react/forbid-elements
        <a
            {...props}
            href={typeof to === 'string' ? to : '#'}
            onClick={onClick}
            target={target}
            rel={target === '_blank' ? 'noopener noreferrer' : undefined}
        />
    )
}
