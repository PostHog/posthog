import { LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

export function ReloadAmountFields(): JSX.Element {
    return (
        <div className="grid grid-cols-3 gap-3 border-t pt-3">
            <LemonField name="lowBalanceThresholdUsd" label="When below">
                <LemonInput type="number" prefix={<span>$</span>} min={0} data-attr="ai-credits-reload-threshold" />
            </LemonField>
            <LemonField name="targetUsd" label="Reload to">
                <LemonInput type="number" prefix={<span>$</span>} min={0} data-attr="ai-credits-reload-target" />
            </LemonField>
            <LemonField name="monthlyReloadLimitUsd" label="Monthly reload limit">
                <LemonInput
                    type="number"
                    prefix={<span>$</span>}
                    min={0}
                    placeholder="No limit"
                    data-attr="ai-credits-reload-limit"
                />
            </LemonField>
        </div>
    )
}
