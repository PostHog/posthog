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
    globals?: Record<string, any>
    disablePersonProperties?: boolean
    disableAutoFocus?: boolean
    disableCmdEnter?: boolean
    submitText?: string
    placeholder?: string
    /** When true, show a hint about using `AS column_name` or `-- column_name` to make
     * long expressions readable as a breakdown/column label. */
    showBreakdownLabelHint?: boolean
}

// Hint is only helpful once the expression is long enough to look unreadable as a column header.
const BREAKDOWN_LABEL_HINT_MIN_LENGTH = 20

// This field takes a SQL expression, not a whole statement. People paste a full query here and get
// a cryptic parse error ("trailing tokens after expression"), so catch the common statement
// keywords up front and explain the difference.
function looksLikeSqlStatement(expression: string): boolean {
    return /^\s*(SELECT|WITH|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\b/i.test(expression)
}

function hasBreakdownLabel(expression: string): boolean {
    // Strip quoted string literals first so a `--` sequence inside a string value
    // (e.g. `if(x = '--disabled', ...)`) doesn't falsely look like a SQL comment.
    const stripped = expression
        .replace(/'(?:[^'\\]|\\.)*'/g, "''")
        .replace(/"(?:[^"\\]|\\.)*"/g, '""')
        .replace(/`(?:[^`\\]|\\.)*`/g, '``')
    // Detects a trailing `AS name` alias or a trailing `-- name` comment label.
    return /\bAS\s+[A-Za-z_][A-Za-z0-9_]*\s*$/i.test(stripped) || /--\s*\S+[^\n]*$/.test(stripped)
}

export function HogQLEditor({
    onChange,
    value,
    metadataSource,
    globals,
    disableAutoFocus,
    disableCmdEnter,
    submitText,
    placeholder,
    showBreakdownLabelHint,
}: HogQLEditorProps): JSX.Element {
    const [bufferedValue, setBufferedValue] = useState(value ?? '')
    useEffect(() => {
        setBufferedValue(value ?? '')
    }, [value])

    const shouldShowBreakdownLabelHint =
        showBreakdownLabelHint &&
        bufferedValue.trim().length > BREAKDOWN_LABEL_HINT_MIN_LENGTH &&
        !hasBreakdownLabel(bufferedValue)

    const isSqlStatement = looksLikeSqlStatement(bufferedValue)

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
                globals={globals}
                onPressCmdEnter={
                    disableCmdEnter || isSqlStatement
                        ? undefined
                        : () => {
                              onChange(bufferedValue)
                          }
                }
            />
            <div className="text-secondary pt-2 text-xs">
                <pre>
                    {placeholder ??
                        (metadataSource && isActorsQuery(metadataSource)
                            ? "Enter SQL expression, such as:\n- properties.$geoip_country_name\n- toInt(properties.$browser_version) * 10\n- concat(properties.name, ' <', properties.email, '>')\n- toBool(is_identified) ? 'user' : 'anon'"
                            : "Enter SQL Expression, such as:\n- properties.$current_url\n- person.properties.email\n- toInt(properties.`Long Field Name`) * 10\n- concat(event, ' ', distinct_id)")}
                </pre>
            </div>
            {shouldShowBreakdownLabelHint && (
                <div className="text-secondary mt-2 text-xs">
                    Tip: add <code>AS column_name</code> or <code>-- column_name</code> to the end of your expression to
                    use a readable label for this breakdown.
                </div>
            )}
            {isSqlStatement && (
                <div className="text-danger mt-2 text-xs">
                    This field takes a SQL expression, not a full query. Enter something like{' '}
                    <code>properties.$browser</code>, not a <code>SELECT</code> statement.
                </div>
            )}
            <LemonButton
                className="mt-2"
                fullWidth
                type="primary"
                onClick={() => onChange(bufferedValue)}
                disabledReason={
                    !bufferedValue
                        ? 'Please enter a SQL expression'
                        : isSqlStatement
                          ? 'Enter a SQL expression, not a full SELECT statement'
                          : null
                }
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
