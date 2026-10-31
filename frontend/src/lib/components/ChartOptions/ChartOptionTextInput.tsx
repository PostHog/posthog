import { LemonInput } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { ChartOptionLabel } from './ChartOptionLabel'
import { QuillChartOptionTextInput } from './QuillChartOptionTextInput'
import { useChartOptionTextDraft } from './useChartOptionTextDraft'

export interface ChartOptionTextInputProps {
    /** Without a label the input fills the row, for a group whose heading already names it. */
    label?: string
    info?: string
    value: string | undefined
    placeholder?: string
    /** Called when the field loses focus or Enter is pressed, with `undefined` for a blank field. */
    onChange: (value: string | undefined) => void
    'data-attr'?: string
}

export function ChartOptionTextInput(props: ChartOptionTextInputProps): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const { draft, setDraft, commit } = useChartOptionTextDraft(props.value, props.onChange)

    if (todayRailNav) {
        return <QuillChartOptionTextInput {...props} draft={draft} setDraft={setDraft} commit={commit} />
    }

    const { label, info, placeholder, 'data-attr': dataAttr } = props
    return (
        <div className="flex flex-col gap-1">
            {label && <ChartOptionLabel label={label} info={info} />}
            <LemonInput
                size="small"
                fullWidth
                value={draft}
                placeholder={placeholder}
                onChange={setDraft}
                onBlur={commit}
                onPressEnter={commit}
                data-attr={dataAttr}
            />
        </div>
    )
}
