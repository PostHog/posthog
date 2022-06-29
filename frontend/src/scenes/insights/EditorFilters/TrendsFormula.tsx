import React, { useEffect, useState } from 'react'
import { EditorFilterProps, FilterType } from '~/types'
import { useActions } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { CloseButton } from 'lib/components/CloseButton'
import { LemonButton } from '@posthog/lemon-ui'
import { IconPlusMini } from 'lib/components/icons'
import { Input } from 'antd'

// When updating this regex, remember to update the regex with the same name in mixins/common.py
const ALLOWED_FORMULA_CHARACTERS = /^[a-zA-Z\ \-\*\^0-9\+\/\(\)\.]+$/

function Formula({
    filters,
    onChange,
    onFocus,
    autoFocus,
    allowClear = true,
}: {
    filters: Partial<FilterType>
    onChange: (formula: string) => void
    onFocus?: (hasFocus: boolean, localFormula: string) => void
    autoFocus?: boolean
    allowClear?: boolean
}): JSX.Element {
    const [value, setValue] = useState(filters.formula)
    useEffect(() => {
        setValue(filters.formula)
    }, [filters.formula])
    return (
        <div style={{ maxWidth: 300 }}>
            <Input.Search
                placeholder="e.g. (A + B)/(A - B) * 100"
                allowClear={allowClear}
                autoFocus={autoFocus}
                value={value}
                onChange={(e) => {
                    let changedValue = e.target.value.toLocaleUpperCase()
                    // Only allow typing of allowed characters
                    changedValue = changedValue
                        .split('')
                        .filter((d) => ALLOWED_FORMULA_CHARACTERS.test(d))
                        .join('')
                    setValue(changedValue)
                }}
                onFocus={() => onFocus && onFocus(true, value)}
                onBlur={() => !filters.formula && onFocus && onFocus(false, value)}
                enterButton="Apply"
                onSearch={onChange}
            />
        </div>
    )
}

export function TrendsFormula({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(trendsLogic(insightProps))
    const [isUsingFormulas, setIsUsingFormulas] = useState(!!filters.formula)

    const formulaEnabled = (filters.events?.length || 0) + (filters.actions?.length || 0) > 0

    return (
        <>
            {isUsingFormulas ? (
                <div className="flex items-center gap-05">
                    <CloseButton
                        onClick={() => {
                            setIsUsingFormulas(false)
                            setFilters({ formula: undefined })
                        }}
                    />
                    <Formula
                        filters={filters}
                        onChange={(formula: string): void => {
                            setFilters({ formula })
                        }}
                        autoFocus
                        allowClear={false}
                    />
                </div>
            ) : (
                <Tooltip
                    title={!formulaEnabled ? 'Please add at least one graph series to use formulas' : undefined}
                    visible={formulaEnabled ? false : undefined}
                >
                    <LemonButton
                        onClick={() => setIsUsingFormulas(true)}
                        disabled={!formulaEnabled}
                        type="secondary"
                        icon={<IconPlusMini color="var(--primary)" />}
                        data-attr="btn-add-formula"
                    >
                        Add formula
                    </LemonButton>
                </Tooltip>
            )}
        </>
    )
}
