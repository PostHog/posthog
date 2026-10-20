import { IconPlus } from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

export interface QuillAddSeriesButtonProps {
    label: string
    onClick: () => void
    disabled: boolean
    variant: 'default' | 'outline' | 'primary'
    fullWidth?: boolean
    icon?: React.ReactNode
    'data-attr': string
}

export function QuillAddSeriesButton({
    label,
    onClick,
    disabled,
    variant,
    fullWidth,
    icon,
    'data-attr': dataAttr,
}: QuillAddSeriesButtonProps): JSX.Element {
    return (
        <Button
            variant={variant}
            onClick={onClick}
            disabled={disabled}
            data-attr={dataAttr}
            className={cn(fullWidth && 'w-full')}
        >
            {icon ?? <IconPlus />}
            {label}
        </Button>
    )
}
