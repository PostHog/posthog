import './SelectableElement.scss'

import clsx from 'clsx'
import { ParsedCSSSelector } from 'lib/components/HTMLElementsDisplay/preselectWithCSS'
import { objectsEqual } from 'lib/utils'

import { ElementType } from '~/types'

export function TagPart({
    tagName,
    selectedParts,
    onChange,
    readonly,
}: {
    tagName: string
    selectedParts: ParsedCSSSelector
    onChange: (s: ParsedCSSSelector) => void
    readonly: boolean
}): JSX.Element {
    const hoverSelector = readonly ? '' : 'hover:underline'
    const htmlElementsSelector = clsx('decoration-primary-highlight', !readonly && 'cursor-pointer SelectableElement')
    const isSelected = !readonly && !!selectedParts.tag

    return (
        <span
            onClick={(e) => {
                e.stopPropagation()
                return onChange({ ...selectedParts, tag: isSelected ? undefined : tagName })
            }}
            className={clsx(htmlElementsSelector, isSelected ? 'SelectableElement--selected' : hoverSelector)}
        >
            {tagName}
        </span>
    )
}

function IdPart({
    id,
    selectedParts,
    onChange,
    readonly,
}: {
    id: string | undefined
    selectedParts: ParsedCSSSelector
    onChange: (s: ParsedCSSSelector) => void
    readonly: boolean
}): JSX.Element | null {
    const hoverSelector = readonly ? '' : 'hover:underline'
    const htmlElementsSelector = clsx('decoration-primary-highlight', !readonly && 'cursor-pointer SelectableElement')
    const isSelected = !readonly && !!selectedParts.id

    return id ? (
        <span
            onClick={(e) => {
                e.stopPropagation()
                return onChange({ ...selectedParts, id: isSelected ? undefined : id })
            }}
            className={clsx(htmlElementsSelector, isSelected ? 'SelectableElement--selected' : hoverSelector)}
        >
            {`id="${id}"`}
        </span>
    ) : null
}

function AttributeValue({
    attribute,
    value,
    selectedParts,
    onChange,
    readonly,
    allowMultipleSelections,
}: {
    attribute: string
    value: string
    selectedParts: ParsedCSSSelector
    onChange: (s: ParsedCSSSelector) => void
    readonly: boolean
    allowMultipleSelections?: boolean
}): JSX.Element {
    const hoverSelector = readonly ? '' : 'hover:underline'
    const htmlElementsSelector = clsx('decoration-primary-highlight', !readonly && 'cursor-pointer SelectableElement')
    const selectionContainer = selectedParts[attribute]
    const isSelected =
        !readonly &&
        (allowMultipleSelections
            ? Array.isArray(selectionContainer) && selectionContainer.includes(value)
            : selectionContainer === value)

    function multipleSelectionsOnChange(): void {
        if (!selectionContainer) {
            onChange({ ...selectedParts, [attribute]: [value] })
        } else if (Array.isArray(selectionContainer)) {
            if (selectionContainer.includes(value)) {
                onChange({
                    ...selectedParts,
                    [attribute]: selectionContainer.filter((p) => p !== value),
                })
            } else {
                onChange({
                    ...selectedParts,
                    [attribute]: [...selectionContainer, value],
                })
            }
        }
    }

    return (
        <>
            <span
                onClick={(e) => {
                    e.stopPropagation()
                    allowMultipleSelections
                        ? multipleSelectionsOnChange()
                        : onChange({ ...selectedParts, [attribute]: isSelected ? undefined : value })
                }}
                className={clsx(htmlElementsSelector, isSelected ? 'SelectableElement--selected' : hoverSelector)}
            >
                {value}
            </span>
        </>
    )
}

function AttributePart({
    attribute,
    values,
    selectedParts,
    onChange,
    readonly,
    allowMultipleSelections,
}: {
    attribute: string
    values: string[]
    selectedParts: ParsedCSSSelector
    onChange: (s: ParsedCSSSelector) => void
    readonly: boolean
    allowMultipleSelections?: boolean
}): JSX.Element {
    const parts = values.map((part) => {
        return (
            <AttributeValue
                key={`${attribute}-${part}`}
                attribute={attribute}
                value={part}
                selectedParts={selectedParts}
                onChange={onChange}
                readonly={readonly}
                allowMultipleSelections={allowMultipleSelections}
            />
        )
    })

    return (
        <>
            {' '}
            {attribute}="{parts.map((part, index) => (index > 0 ? <> {part}</> : part))}"
        </>
    )
}

export function SelectableElement({
    element,
    isDeepestChild,
    onChange,
    readonly,
    indent,
    highlight,
    parsedCSSSelector,
}: {
    element: ElementType
    isDeepestChild: boolean
    onChange: (selector: ParsedCSSSelector) => void
    readonly: boolean
    indent: string
    highlight?: boolean
    parsedCSSSelector?: ParsedCSSSelector
}): JSX.Element {
    const setParsedCSSSelector = (newParsedCSSSelector: ParsedCSSSelector): void => {
        if (!objectsEqual(newParsedCSSSelector, parsedCSSSelector)) {
            onChange(newParsedCSSSelector)
        }
    }

    return (
        <pre
            className={clsx(
                'p-0 m-0 rounded whitespace-pre-wrap break-all text-white text-sm',
                isDeepestChild && highlight ? 'bg-brand-red' : 'bg-transparent'
            )}
        >
            {indent}
            &lt;
            <TagPart
                tagName={element.tag_name}
                selectedParts={parsedCSSSelector || ({} as ParsedCSSSelector)}
                readonly={readonly}
                onChange={setParsedCSSSelector}
            />
            {element.attr_id && ' '}
            <IdPart
                id={element.attr_id}
                selectedParts={parsedCSSSelector || ({} as ParsedCSSSelector)}
                readonly={readonly}
                onChange={setParsedCSSSelector}
            />
            {Object.entries(element.attributes ?? {})
                .filter(([key]) => key !== 'style' && key !== 'value')
                .map(([key, value]) => {
                    const attrName: string = key.replace('attr__', '')
                    return (
                        <AttributePart
                            key={`${indent.length}-${element.tag_name}-${attrName}-${value}`}
                            attribute={attrName}
                            values={value.split(' ')}
                            selectedParts={parsedCSSSelector || ({} as ParsedCSSSelector)}
                            onChange={setParsedCSSSelector}
                            readonly={readonly}
                            allowMultipleSelections={attrName === 'class'}
                        />
                    )
                })}
            &gt;
            {element.text}
            {isDeepestChild && <span>&lt;/{element.tag_name}&gt;</span>}
        </pre>
    )
}
