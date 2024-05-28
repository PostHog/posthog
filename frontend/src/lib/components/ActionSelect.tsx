import { LemonButtonProps } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { actionLogic } from 'scenes/actions/actionLogic'

interface LemonSelectActionProps {
    value?: number | null
    onChange?: (value: number | null) => void
    disabled?: boolean
    placeholder?: string
    allowClear?: boolean
    size?: LemonButtonProps['size']
    fullWidth?: boolean
}

export function LemonSelectAction({
    value,
    onChange = () => {},
    disabled,
    placeholder = 'Select an action',
    allowClear,
    size,
}: LemonSelectActionProps): JSX.Element {
    const { action } = useValues(actionLogic({ id: value ?? undefined }))

    return (
        <TaxonomicPopover
            groupType={TaxonomicFilterGroupType.Actions}
            onChange={onChange}
            disabled={disabled}
            value={value}
            type="secondary"
            placeholder={placeholder}
            data-attr="event-name-box"
            renderValue={(v) =>
                v !== null ? (
                    <>
                        <span>{value} - </span>
                        <span>{action?.name ?? 'Loading...'}</span>
                    </>
                ) : null
            }
            allowClear={allowClear}
            size={size}
            fullWidth
        />
    )
}
