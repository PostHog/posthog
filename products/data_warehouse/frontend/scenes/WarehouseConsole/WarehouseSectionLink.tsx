import { IconArrowRight } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

/** A navigation link for a section header: link-style button with a trailing arrow. */
export function WarehouseSectionLink({
    to,
    children,
    onClick,
    'data-attr': dataAttr,
}: {
    to: string
    children: React.ReactNode
    onClick?: () => void
    'data-attr': string
}): JSX.Element {
    return (
        <Button
            variant="link"
            size="sm"
            nativeButton={false}
            render={<LinkPrimitive to={to} onClick={onClick} data-attr={dataAttr} />}
        >
            {children}
            <IconArrowRight />
        </Button>
    )
}
