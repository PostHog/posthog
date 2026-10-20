import { LemonSwitch } from '@posthog/lemon-ui'

import { FormulaModeSwitchProps } from './formulaModeSwitch'

export function LemonFormulaModeSwitch({ checked, onChange, disabled }: FormulaModeSwitchProps): JSX.Element {
    return (
        <LemonSwitch
            className="mt-2"
            checked={checked}
            onChange={onChange}
            disabled={disabled}
            label="Formula mode"
            bordered
            id="trends-formula-switch"
            data-attr="trends-formula-switch"
        />
    )
}
