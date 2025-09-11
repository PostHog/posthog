import { useEffect, useState } from 'react'

import { Link } from '@posthog/lemon-ui'

import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'

import { AnyDataNode } from '~/queries/schema/schema-general'
import { isActorsQuery } from '~/queries/utils'

export interface HogQLEditorProps {
    onChange: (value: string) => void
    value: string | undefined | null
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
            <div className="text-secondary pt-2 text-xs">
                <pre>
                    {placeholder ??
                        (metadataSource && isActorsQuery(metadataSource)
                            ? "Enter SQL expression, such as:\n- properties.$geoip_country_name\n- toInt(properties.$browser_version) * 10\n- concat(properties.name, ' <', properties.email, '>')\n- is_identified ? 'user' : 'anon'"
                            : "Enter SQL Expression, such as:\n- properties.$current_url\n- person.properties.$geoip_country_name\n- pdi.person.properties.email\n- toInt(properties.`Long Field Name`) * 10\n- concat(event, ' ', distinct_id)")}
                </pre>
            </div>
            <LemonButton
                className="mt-2"
                fullWidth
                type="primary"
                onClick={() => onChange(bufferedValue)}
                disabledReason={!bufferedValue ? 'Please enter a SQL expression' : null}
                center
            >
                {submitText ?? 'Update SQL expression'}
            </LemonButton>
            <div className="flex mt-1 gap-1">
                <div className={`w-full text-right select-none ${CLICK_OUTSIDE_BLOCK_CLASS}`}>
                    <Link to="https://posthog.com/docs/sql" target="_blank">
                        Learn more about SQL
                    </Link>
                </div>
            </div>
        </>
    )
}
