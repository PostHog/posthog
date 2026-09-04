import { useActions } from 'kea'

import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { LemonSwitchProps } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'

import { FilterType } from '~/types'

export function TestAccountFilter({
    filters,
    size,
    onChange,
    disabledReason,
}: {
    filters: Partial<FilterType>
    size?: LemonSwitchProps['size']
    onChange: (filters: Partial<FilterType>) => void
    disabledReason?: string | null | false
}): JSX.Element | null {
    const { setLocalDefault } = useActions(filterTestAccountsDefaultsLogic)

    return (
        <TestAccountFilterSwitch
            checked={!!filters.filter_test_accounts}
            onChange={(checked: boolean) => {
                onChange({ filter_test_accounts: checked })
                setLocalDefault(checked)
            }}
            size={size}
            fullWidth
            disabledReason={disabledReason}
        />
    )
}
