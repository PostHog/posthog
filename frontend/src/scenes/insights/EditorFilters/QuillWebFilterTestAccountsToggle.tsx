import { QuillLabeledSwitch } from 'lib/components/QuillLabeledSwitch/QuillLabeledSwitch'

export interface QuillWebFilterTestAccountsToggleProps {
    checked: boolean
    onChange: (checked: boolean) => void
}

export function QuillWebFilterTestAccountsToggle({
    checked,
    onChange,
}: QuillWebFilterTestAccountsToggleProps): JSX.Element {
    return (
        <QuillLabeledSwitch
            checked={checked}
            onChange={onChange}
            label="Filter out internal and test users"
            tooltip="Filter out events from test accounts"
        />
    )
}
