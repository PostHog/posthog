import { useEffect, useState } from 'react'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
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
                placeholder={
                    'Enter HogQL Expression, such as:\n- properties.$current_url\n- count()\n- sum(toInt(properties.$screen_width)) * 10\n- concat(event, " ", distinct_id)\n- ifElse(1 < 2, "small", "large")'
                }
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
                {value ? 'Update HogQL expression' : 'Add HogQL expression'}
            </LemonButton>
            <div className="text-right">
                <a href="https://github.com/PostHog/meta/issues/86" target={'_blank'}>
                    Learn more about HogQL
                </a>
            </div>
        </div>
    )
}
