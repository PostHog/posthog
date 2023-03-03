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
                data-attr="inline-hogql-editor"
                value={String(localValue ?? '')}
                onChange={(e) => setLocalValue(e)}
                className="font-mono"
                minRows={6}
                maxRows={6}
                placeholder={
                    'Enter HogQL Expression, such as:\n- properties.$current_url\n- person.properties.$geoip_country_name\n- toInt(properties.$screen_width) * 10\n- concat(event, " ", distinct_id)\n- if(1 < 2, "small", "large")'
                }
                // :TRICKY: No autofocus here. It's controlled in the TaxonomicFilter.
                // autoFocus
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
                <a href="https://posthog.com/manual/hogql" target={'_blank'}>
                    Learn more about HogQL
                </a>
            </div>
        </div>
    )
}
