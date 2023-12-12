import clsx from 'clsx'
import { IconCopy } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

interface InlinePropsBase {
    description?: string
    /** Makes text selectable instead of copying on click anywhere */
    selectable?: boolean
    isValueSensitive?: boolean
    tooltipMessage?: string | null
    iconStyle?: Record<string, string | number>
    iconPosition?: 'end' | 'start'
    className?: string
    /** @deprecated */
    style?: React.CSSProperties
}
interface InlinePropsWithStringInside extends InlinePropsBase {
    children: string
    explicitValue?: string
}
interface InlinePropsWithJSXInside extends InlinePropsBase {
    children?: JSX.Element
    explicitValue: string
}
type InlineProps = InlinePropsWithStringInside | InlinePropsWithJSXInside

export function CopyToClipboardInline({
    children,
    explicitValue,
    description,
    selectable = false,
    isValueSensitive = false,
    tooltipMessage = null,
    iconStyle,
    iconPosition = 'end',
    className,
    style,
    ...props
}: InlineProps): JSX.Element {
    const copy = async (): Promise<boolean> => await copyToClipboard((explicitValue ?? children) as string, description)

    let content = (
        <LemonButton
            size="small"
            icon={<IconCopy style={{ ...iconStyle }} />}
            noPadding
            className="ml-1"
            data-attr="copy-icon"
            onClick={!selectable ? undefined : copy}
        />
    )

    if (children) {
        content = (
            <span
                className={clsx(
                    'relative truncate inline-flex items-center flex-nowrap w-fit break-all',
                    selectable ? 'cursor-text' : 'cursor-pointer',
                    iconPosition === 'end' ? 'flex-row' : 'flex-row-reverse',
                    isValueSensitive && 'ph-no-capture',
                    className
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={style}
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
    }
    return !selectable || tooltipMessage !== null ? (
        <Tooltip title={tooltipMessage || 'Click to copy'}>{content}</Tooltip>
    ) : (
        <>{content}</>
    )
}
