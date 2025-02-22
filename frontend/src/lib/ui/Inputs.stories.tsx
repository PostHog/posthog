import { LemonCheckbox, LemonSwitch } from '@posthog/lemon-ui'
import { Meta } from '@storybook/react'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio/LemonRadio'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider/LemonSlider'
import { useState } from 'react'

const meta: Meta = {
    title: 'Design System/Inputs',
    tags: ['autodocs'],
}
export default meta

function GetAllInputs(): JSX.Element {
    const [checked, setChecked] = useState(false)
    const [radioValue, setRadioValue] = useState('this')

    return (
        <div className="flex flex-col gap-2">
            <LemonInput />
            <LemonInput placeholder="Placeholder" />
            <LemonInput disabled />
            <LemonInput disabled />
            <LemonInput value={"I'm pre-filled"} />
            <LemonSlider max={100} min={0} value={50} />
            <LemonCheckbox label="Checkbox" />
            <LemonCheckbox label="Checkbox" disabledReason="This is not the way to Amarillo" />
            <LemonCheckbox label="Checkbox" checked />
            <LemonRadio
                value={radioValue}
                options={[
                    { label: 'This', value: 'this' },
                    { label: 'That', value: 'that' },
                ]}
                onChange={setRadioValue}
            />
            <LemonRadio
                value={radioValue}
                options={[
                    { label: 'This', value: 'this', disabledReason: 'This is not the way to Amarillo' },
                    { label: 'That', value: 'that' },
                ]}
                onChange={setRadioValue}
            />
            <LemonSwitch checked={checked} onChange={() => setChecked(!checked)} />
            <LemonSwitch checked={checked} bordered onChange={() => setChecked(!checked)} />
            <LemonSwitch checked={true} disabledReason="This is not the way to Amarillo" />
            <LemonSwitch checked={false} />
            <LemonSwitch checked={false} bordered />
            <LemonSwitch checked={false} disabledReason="This is not the way to Amarillo" />
        </div>
    )
}

export const AllInputs = (): JSX.Element => {
    return (
        <div className="space-y-2">
            <div className="bg-primary p-4">{GetAllInputs()}</div>
            <div className="bg-surface-primary p-4">{GetAllInputs()}</div>
            <div className="bg-surface-secondary p-4">{GetAllInputs()}</div>
            <div className="bg-surface-tertiary p-4">{GetAllInputs()}</div>
        </div>
    )
}
