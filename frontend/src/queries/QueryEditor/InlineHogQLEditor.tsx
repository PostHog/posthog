import { useEffect, useState } from 'react'
import { LemonTextArea } from 'lib/components/LemonTextArea/LemonTextArea'
import { LemonButton } from 'lib/components/LemonButton'
import { TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'

export interface InlineHogQLEditorProps {
    value?: TaxonomicFilterValue
    onChange: (value: TaxonomicFilterValue) => void
}

export function InlineHogQLEditor({ value, onChange }: InlineHogQLEditorProps): JSX.Element {
    const [localValue, setLocalValue] = useState(value)
    useEffect(() => {
        setLocalValue(value)
    }, [value])
    return (
        <div className="px-2">
            <LemonTextArea
                value={String(localValue ?? '')}
                onChange={(e) => setLocalValue(e)}
                className="font-mono"
                minRows={6}
                maxRows={6}
                placeholder={'Enter HogQL Expression...'}
                autoFocus
            />
            <LemonButton
                fullWidth
                type="primary"
                onClick={() => {
                    onChange(String(localValue))
                    setLocalValue('')
                }}
                disabled={!localValue}
                center
            >
                {value ? 'Edit HogQL expression' : 'Add HogQL expression'}
            </LemonButton>
        </div>
    )
}
