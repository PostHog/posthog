import { useEffect, useState } from 'react'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconInfo } from 'lib/lemon-ui/icons'

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
                minRows={3}
                maxRows={6}
                placeholder={
                    placeholder ??
                    (disablePersonProperties
                        ? "Enter HogQL expression, such as:\n- properties.$current_url\n- toInt(properties.`Long Field Name`) * 10\n- concat(event, ' ', distinct_id)\n- if(1 < 2, 'small', 'large')"
                        : "Enter HogQL Expression, such as:\n- properties.$current_url\n- person.properties.$geoip_country_name\n- toInt(properties.`Long Field Name`) * 10\n- concat(event, ' ', distinct_id)\n- if(1 < 2, 'small', 'large')")
                }
            />
            <LemonButton
                className="mt-2"
                fullWidth
                type="primary"
                onClick={() => onChange(localValue)}
                disabledReason={!localValue ? 'Please enter a HogQL expression' : undefined}
                center
            >
                {submitText ?? 'Update HogQL expression'}
            </LemonButton>
            <div className="flex mt-1 gap-1">
                {disablePersonProperties ? (
                    <div className="flex-1 flex items-center text-muted select-none">
                        <IconInfo className="text-base mr-1" />
                        <span>
                            <code>person.properties</code> can't be used here.
                        </span>
                    </div>
                ) : null}
                <div
                    className={`${
                        disablePersonProperties ? '' : 'w-full '
                    }text-right select-none ${CLICK_OUTSIDE_BLOCK_CLASS}`}
                >
                    <a href="https://posthog.com/manual/hogql" target={'_blank'}>
                        Learn more about HogQL
                    </a>
                </div>
            </div>
        </>
    )
}
