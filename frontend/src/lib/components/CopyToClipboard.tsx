import { HTMLProps } from 'react'
import { copyToClipboard } from 'lib/utils'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconCopy } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

interface InlineProps extends HTMLProps<HTMLSpanElement> {
    children?: JSX.Element | string
    explicitValue?: string
    description?: string
    /** Makes text selectable instead of copying on click anywhere */
    selectable?: boolean
    isValueSensitive?: boolean
    tooltipMessage?: string | null
    iconStyle?: Record<string, string | number>
    iconPosition?: 'end' | 'start'
    style?: React.CSSProperties
}

export function CopyToClipboardInline({
    children,
    explicitValue,
    description,
    selectable = false,
    isValueSensitive = false,
    tooltipMessage = null,
    iconStyle,
    iconPosition = 'end',
    style,
    ...props
}: InlineProps): JSX.Element {
    const copy = async (): Promise<boolean> =>
        await copyToClipboard(explicitValue ?? (children ? children.toString() : ''), description)

    const content = (
        <span
            className={isValueSensitive ? 'ph-no-capture' : ''}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                position: 'relative',
                overflow: 'hidden',
                cursor: selectable ? 'text' : 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                flexDirection: iconPosition === 'end' ? 'row' : 'row-reverse',
                flexWrap: 'nowrap',
                width: 'fit-content',
                wordBreak: 'break-all',
                ...style,
            }}
            onClick={!selectable ? copy : undefined}
            {...props}
        >
            <span className={iconPosition === 'start' ? 'grow-1' : undefined}>{children}</span>
            <LemonButton
                size="small"
                icon={<IconCopy style={{ ...iconStyle }} />}
                noPadding
                className="ml-1"
                data-attr="copy-icon"
                onClick={!selectable ? undefined : copy}
            />
        </span>
    )
    return !selectable || tooltipMessage !== null ? (
        <Tooltip title={tooltipMessage || 'Click to copy'}>{content}</Tooltip>
    ) : (
        <>{content}</>
    )
}
