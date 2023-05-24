import { useEffect, useState } from 'react'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

export interface HogQLEditorProps {
    onChange: (value: string) => void
    value: string | undefined
    disablePersonProperties?: boolean
    disableAutoFocus?: boolean
    disableCmdEnter?: boolean
    submitText?: string
    placeholder?: string
}

export function HogQLEditor({
    onChange,
    value,
    disablePersonProperties,
    disableAutoFocus,
    disableCmdEnter,
    submitText,
    placeholder,
}: HogQLEditorProps): JSX.Element {
    const [localValue, setLocalValue] = useState(value || '')
    useEffect(() => {
        setLocalValue(value || '')
    }, [value])

    return (
        <>
            <LemonTextArea
                data-attr="inline-hogql-editor"
                value={localValue || ''}
                onChange={(newValue) => setLocalValue(newValue)}
                autoFocus={!disableAutoFocus}
                onFocus={
                    disableAutoFocus
                        ? undefined
                        : (e) => {
                              e.target.selectionStart = localValue.length // Focus at the end of the input
                          }
                }
                onPressCmdEnter={disableCmdEnter ? undefined : () => onChange(localValue)}
                className={`font-mono ${CLICK_OUTSIDE_BLOCK_CLASS}`}
                minRows={6}
                maxRows={6}
                placeholder={
                    placeholder ??
                    (disablePersonProperties
                        ? "Enter HogQL expression, such as:\n- properties.$current_url\n- toInt(properties.`Long Field Name`) * 10\n- concat(event, ' ', distinct_id)\n- if(1 < 2, 'small', 'large')"
                        : "Enter HogQL Expression, such as:\n- properties.$current_url\n- person.properties.$geoip_country_name\n- toInt(properties.`Long Field Name`) * 10\n- concat(event, ' ', distinct_id)\n- if(1 < 2, 'small', 'large')")
                }
            />
            <LemonButton
                fullWidth
                type="primary"
                onClick={() => onChange(localValue)}
                disabledReason={!localValue ? 'Please enter a HogQL expression' : undefined}
                center
            >
                {submitText ?? 'Update HogQL expression'}
            </LemonButton>
            <div className="flex">
                {disablePersonProperties ? (
                    <div className="flex-1 text-muted">NB: person.properties can't be used here.</div>
                ) : null}
                <div className={`${disablePersonProperties ? '' : 'w-full '}text-right ${CLICK_OUTSIDE_BLOCK_CLASS}`}>
                    <a href="https://posthog.com/manual/hogql" target={'_blank'}>
                        Learn more about HogQL
                    </a>
                </div>
            </div>
        </>
    )
}
