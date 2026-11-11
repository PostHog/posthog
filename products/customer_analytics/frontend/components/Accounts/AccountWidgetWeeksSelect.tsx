import { LemonSelect } from '@posthog/lemon-ui'

import { AccountViewTileHeaderActions } from '../../scenes/CustomerAnalyticsAccountScene/AccountViewTileHeaderActions'
import { ACCOUNT_WIDGET_WEEKS, type AccountWidgetWeeks } from './accountWidgetWeeks'

export function AccountWidgetWeeksSelect({
    weeks,
    onChange,
}: {
    weeks: AccountWidgetWeeks
    onChange: (weeks: AccountWidgetWeeks) => void
}): JSX.Element {
    return (
        <AccountViewTileHeaderActions>
            <LemonSelect
                size="small"
                value={weeks}
                onChange={onChange}
                options={ACCOUNT_WIDGET_WEEKS.map((value) => ({ value, label: `Last ${value} weeks` }))}
                data-attr="account-widget-weeks"
            />
        </AccountViewTileHeaderActions>
    )
}
