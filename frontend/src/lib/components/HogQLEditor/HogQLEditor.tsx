import { Link } from '@posthog/lemon-ui'
import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { useEffect, useState } from 'react'

import { AnyDataNode } from '~/queries/schema'
import { isActorsQuery } from '~/queries/utils'

export interface HogQLEditorProps {
    onChange: (value: string) => void
    value: string | undefined
    metadataSource?: AnyDataNode
    disablePersonProperties?: boolean
    disableAutoFocus?: boolean
    disableCmdEnter?: boolean
    submitText?: string
    placeholder?: string
}

export function HogQLEditor({
    onChange,
    value,
    metadataSource,
    disableAutoFocus,
    disableCmdEnter,
    submitText,
    placeholder,
}: HogQLEditorProps): JSX.Element {
    const [bufferedValue, setBufferedValue] = useState(value ?? '')
    useEffect(() => {
        setBufferedValue(value ?? '')
    }, [value])

    return (
        <>
            <CodeEditorInline
                data-attr="inline-hogql-editor"
                value={bufferedValue || ''}
                onChange={(newValue) => {
                    setBufferedValue(newValue ?? '')
                }}
                language="hogQLExpr"
                className={CLICK_OUTSIDE_BLOCK_CLASS}
                minHeight="78px"
                autoFocus={!disableAutoFocus}
                sourceQuery={metadataSource}
                onPressCmdEnter={
                    disableCmdEnter
                        ? undefined
                        : (value) => {
                              onChange(value)
                          }
                }
            />
            <div className="text-muted pt-2 text-xs">
                <pre>
                    {placeholder ??
                        (metadataSource && isActorsQuery(metadataSource)
                            ? "Enter HogQL expression, such as:\n- properties.$geoip_country_name\n- toInt(properties.$browser_version) * 10\n- concat(properties.name, ' <', properties.email, '>')\n- is_identified ? 'user' : 'anon'"
                            : "Enter HogQL Expression, such as:\n- properties.$current_url\n- person.properties.$geoip_country_name\n- toInt(properties.`Long Field Name`) * 10\n- concat(event, ' ', distinct_id)\n- if(1 < 2, 'small', 'large')")}
                </pre>
            </div>
            <LemonButton
                className="mt-2"
                fullWidth
                type="primary"
                onClick={() => onChange(bufferedValue)}
                disabledReason={!bufferedValue ? 'Please enter a HogQL expression' : null}
                center
            >
                {submitText ?? 'Update HogQL expression'}
            </LemonButton>
            <div className="flex mt-1 gap-1">
                <div className={`w-full text-right select-none ${CLICK_OUTSIDE_BLOCK_CLASS}`}>
                    <Link to="https://posthog.com/manual/hogql" target="_blank">
                        Learn more about HogQL
                    </Link>
                </div>
            </div>
        </>
    )
}
