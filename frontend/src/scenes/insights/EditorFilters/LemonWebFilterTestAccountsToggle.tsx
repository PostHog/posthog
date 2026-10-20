import { IconFilter } from '@posthog/icons'
import { LemonButton, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

export interface WebFilterTestAccountsToggleProps {
    checked: boolean
    onChange: (checked: boolean) => void
}

export function LemonWebFilterTestAccountsToggle({ checked, onChange }: WebFilterTestAccountsToggleProps): JSX.Element {
    return (
        <Tooltip title="Filter out events from test accounts">
            <LemonButton icon={<IconFilter />} onClick={() => onChange(!checked)} type="secondary" size="small">
                Filter out internal and test users: <LemonSwitch checked={checked} className="ml-1" />
            </LemonButton>
        </Tooltip>
    )
}
