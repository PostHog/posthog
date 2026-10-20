import { QuillLabeledSwitch } from 'lib/components/QuillLabeledSwitch/QuillLabeledSwitch'

import { FormulaModeSwitchProps } from './formulaModeSwitch'

export function QuillFormulaModeSwitch({ checked, onChange, disabled }: FormulaModeSwitchProps): JSX.Element {
    return (
        <QuillLabeledSwitch
            className="mt-2"
            checked={checked}
            onChange={onChange}
            disabled={disabled}
            label="Formula mode"
            id="trends-formula-switch"
            data-attr="trends-formula-switch"
        />
    )
}
