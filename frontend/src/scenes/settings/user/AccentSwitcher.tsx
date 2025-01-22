import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { useState } from 'react'

export function AccentSwitcher(): JSX.Element {
    const [accent, setAccent] = useState('blue')

    const accentOptions: LemonRadioOption<string>[] = [
        { value: 'blue', label: 'Blue   ' },
        { value: 'green', label: 'Green' },
        { value: 'red', label: 'Red' },
    ]

    return <LemonRadio options={accentOptions} onChange={setAccent} value={accent} radioPosition="top" />
}
