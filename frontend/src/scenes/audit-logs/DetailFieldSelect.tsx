import { useMemo, useState } from 'react'

import { LemonSearchableSelect, LemonSelectOption, LemonSelectSection } from '@posthog/lemon-ui'

import { midEllipsis } from 'lib/utils/strings'

import { DetailFieldChoice, VisibleDetailFieldChoice, getVisibleDetailFieldChoices } from './detailFieldChoices'

export interface DetailFieldSelectProps {
    choices: DetailFieldChoice[]
    excludedFieldPaths: string[]
    value?: string
    onChange: (fieldPath: string) => void
    placeholder: string
    icon?: JSX.Element
    extraSections?: LemonSelectSection<string>[]
    className?: string
    'data-attr'?: string
}

const NO_EXTRA_SECTIONS: LemonSelectSection<string>[] = []
const EMPTY_STATE_VALUE = '__no_fields__'

function emptyStateOption(message: string): LemonSelectOption<string> {
    return {
        value: EMPTY_STATE_VALUE,
        label: message,
        labelInMenu: function EmptyState() {
            return <div className="px-2 py-1.5 text-secondary">{message}</div>
        },
    }
}

const NO_MATCH_OPTION = emptyStateOption('No matching fields. Try a different search.')
const NO_FIELDS_LEFT_OPTION = emptyStateOption('No more fields available.')

function choiceToOption(choice: VisibleDetailFieldChoice): LemonSelectOption<string> {
    const { fieldName } = choice
    const scopeNames = choice.scopes.map((scope) => scope.replace(/([A-Z])/g, ' $1').trim()).join(', ')

    return {
        value: choice.value,
        label: (
            <div className="flex flex-col">
                <div>{choice.leafName}</div>
                <div className="text-xs text-muted">
                    {fieldName.length > 50 ? midEllipsis(fieldName, 50) : fieldName}
                </div>
            </div>
        ),
        tooltip: (
            <div className="text-xs">
                <div>
                    <strong>Full path:</strong>
                    <br />
                    {fieldName}
                </div>
                <br />
                <div>
                    <strong>Available in:</strong>
                    <br />
                    {scopeNames}
                </div>
            </div>
        ),
    }
}

function truncationNote(shown: number, matchCount: number, isSearching: boolean): string {
    const counts = `Showing ${shown.toLocaleString()} of ${matchCount.toLocaleString()}`
    return isSearching
        ? `${counts} matching fields. Type more to narrow the list.`
        : `${counts} fields. Search to find more.`
}

export function DetailFieldSelect({
    choices,
    excludedFieldPaths,
    value,
    onChange,
    placeholder,
    icon,
    extraSections = NO_EXTRA_SECTIONS,
    className,
    'data-attr': dataAttr,
}: DetailFieldSelectProps): JSX.Element {
    const [searchTerm, setSearchTerm] = useState('')

    const options = useMemo(() => {
        const { visible, selected, matchCount } = getVisibleDetailFieldChoices(choices, {
            searchTerm,
            excludedFieldPaths,
            selectedFieldPath: value,
        })

        const fieldOptions = visible.map(choiceToOption)
        if (fieldOptions.length === 0) {
            fieldOptions.push(searchTerm.trim() ? NO_MATCH_OPTION : NO_FIELDS_LEFT_OPTION)
        }
        if (selected && !visible.some((choice) => choice.isSelected)) {
            fieldOptions.push({ ...choiceToOption(selected), hidden: true })
        }

        const fieldSection: LemonSelectSection<string> = {
            title: 'Available fields',
            options: fieldOptions,
            footer:
                matchCount > visible.length ? (
                    <div className="px-2 py-1.5 text-xs text-secondary">
                        {truncationNote(visible.length, matchCount, !!searchTerm.trim())}
                    </div>
                ) : undefined,
        }
        return [fieldSection, ...extraSections]
    }, [choices, searchTerm, excludedFieldPaths, value, extraSections])

    return (
        <LemonSearchableSelect
            value={value}
            onChange={(newValue) => {
                if (newValue && newValue !== EMPTY_STATE_VALUE) {
                    onChange(newValue)
                }
            }}
            options={options}
            filterOptionsLocally={false}
            onSearchChange={setSearchTerm}
            placeholder={placeholder}
            searchPlaceholder="Search fields..."
            searchInputDataAttr={dataAttr ? `${dataAttr}-search` : undefined}
            icon={icon}
            size="small"
            className={className}
            data-attr={dataAttr}
        />
    )
}
