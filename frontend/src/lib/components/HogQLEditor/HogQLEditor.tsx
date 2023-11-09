import { useRef, useState } from 'react'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconErrorOutline, IconInfo } from 'lib/lemon-ui/icons'
import { useActions, useValues } from 'kea'
import { hogQLEditorLogic } from './hogQLEditorLogic'
import { Link } from '@posthog/lemon-ui'

export interface HogQLEditorProps {
    onChange: (value: string) => void
    value: string | undefined
    hogQLTable?: string
    disablePersonProperties?: boolean
    disableAutoFocus?: boolean
    disableCmdEnter?: boolean
    submitText?: string
    placeholder?: string
}
let uniqueNode = 0

export function HogQLEditor({
    onChange,
    value,
    hogQLTable,
    disablePersonProperties,
    disableAutoFocus,
    disableCmdEnter,
    submitText,
    placeholder,
}: HogQLEditorProps): JSX.Element {
    const [key] = useState(() => `HogQLEditor.${uniqueNode++}`)
    const textareaRef = useRef<HTMLTextAreaElement | null>(null)
    const logic = hogQLEditorLogic({ key, value, onChange, hogQLTable, textareaRef })
    const { localValue, error, responseLoading } = useValues(logic)
    const { setLocalValue, submit } = useActions(logic)

    return (
        <>
            <LemonTextArea
                data-attr="inline-hogql-editor"
                value={localValue || ''}
                onChange={(newValue) => setLocalValue(newValue)}
                autoFocus={!disableAutoFocus}
                ref={textareaRef}
                onFocus={
                    disableAutoFocus
                        ? undefined
                        : (e) => {
                              e.target.selectionStart = localValue.length // Focus at the end of the input
                          }
                }
                onPressCmdEnter={disableCmdEnter ? undefined : submit}
                className={`font-mono ${CLICK_OUTSIDE_BLOCK_CLASS}`}
                minRows={3}
                maxRows={6}
                placeholder={
                    placeholder ??
                    (hogQLTable === 'persons'
                        ? "Enter HogQL expression, such as:\n- properties.$geoip_country_name\n- toInt(properties.$browser_version) * 10\n- concat(properties.name, ' <', properties.email, '>')\n- is_identified ? 'user' : 'anon'"
                        : disablePersonProperties
                        ? "Enter HogQL expression, such as:\n- properties.$current_url\n- toInt(properties.`Long Field Name`) * 10\n- concat(event, ' ', distinct_id)\n- if(1 < 2, 'small', 'large')"
                        : "Enter HogQL Expression, such as:\n- properties.$current_url\n- person.properties.$geoip_country_name\n- toInt(properties.`Long Field Name`) * 10\n- concat(event, ' ', distinct_id)\n- if(1 < 2, 'small', 'large')")
                }
            />
            {error ? (
                <div className="text-danger flex mt-1 gap-1 text-sm max-h-20 overflow-auto">
                    <IconErrorOutline className="text-xl" />
                    <span>{error}</span>
                </div>
            ) : null}
            <LemonButton
                className="mt-2"
                fullWidth
                type="primary"
                onClick={submit}
                loading={responseLoading}
                disabledReason={!localValue ? 'Please enter a HogQL expression' : error ? 'Please fix the error' : null}
                center
            >
                {submitText ?? 'Update HogQL expression'}
            </LemonButton>
            <div className="flex mt-1 gap-1">
                {disablePersonProperties ? (
                    <div className="flex-1 flex items-center text-muted select-none">
                        <IconInfo className="text-base mr-1" />
                        <span>
                            <code>person</code> can't be used here.
                        </span>
                    </div>
                ) : null}
                <div
                    className={`${
                        disablePersonProperties ? '' : 'w-full '
                    }text-right select-none ${CLICK_OUTSIDE_BLOCK_CLASS}`}
                >
                    <Link to="https://posthog.com/manual/hogql" target="_blank">
                        Learn more about HogQL
                    </Link>
                </div>
            </div>
        </>
    )
}
