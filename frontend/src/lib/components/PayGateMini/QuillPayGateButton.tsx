import { Button } from '@posthog/quill'

import type { LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { quillButtonVariant } from 'lib/lemon-ui/LemonButton/quillButtonVariant'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

export function QuillPayGateButton({
    type,
    to,
    onClick,
    disabledReason,
    dataAttr,
    children,
}: {
    type: LemonButtonProps['type']
    to: string | undefined
    onClick: LemonButtonProps['onClick']
    disabledReason: LemonButtonProps['disabledReason']
    dataAttr: string | undefined
    children: React.ReactNode
}): JSX.Element {
    return (
        <Button
            variant={quillButtonVariant(type ?? 'primary')}
            onClick={onClick}
            nativeButton={!to}
            render={to ? <LinkPrimitive to={to} /> : undefined}
            disabledReason={disabledReason}
            data-attr={dataAttr}
        >
            {children}
        </Button>
    )
}
