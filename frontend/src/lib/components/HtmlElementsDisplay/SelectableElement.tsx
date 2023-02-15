import { ElementType } from '~/types'
import clsx from 'clsx'
import { useEffect, useState } from 'react'
import './SelectableElement.scss'
type SelectedParts = Record<string, string | Set<string> | undefined>

export function TagPart({
    tagName,
    selectedParts,
    onChange,
    readonly,
}: {
    tagName: string
    selectedParts: SelectedParts
    onChange: (s: SelectedParts) => void
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
    selectedParts: SelectedParts
    onChange: (s: SelectedParts) => void
    readonly: boolean
}): JSX.Element | null {
    const hoverSelector = readonly ? '' : 'hover:underline'
    const htmlElementsSelector = clsx('decoration-primary-highlight', !readonly && 'cursor-pointer SelectableElement')
    const isSelected = !readonly && !!selectedParts.id

    return !!id ? (
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
    selectedParts: SelectedParts
    onChange: (s: SelectedParts) => void
    readonly: boolean
    allowMultipleSelections?: boolean
}): JSX.Element {
    const hoverSelector = readonly ? '' : 'hover:underline'
    const htmlElementsSelector = clsx('decoration-primary-highlight', !readonly && 'cursor-pointer SelectableElement')
    const selectionContainer = selectedParts[attribute]
    const isSelected =
        !readonly &&
        (allowMultipleSelections
            ? selectionContainer instanceof Set && selectionContainer.has(value)
            : selectionContainer === value)

    function multipleSelectionsOnChange(): void {
        if (!selectionContainer) {
            onChange({ ...selectedParts, [attribute]: new Set([value]) })
        } else if (selectionContainer instanceof Set) {
            if (selectionContainer.has(value)) {
                onChange({
                    ...selectedParts,
                    [attribute]: new Set(Array.from(selectionContainer).filter((p) => p !== value)),
                })
            } else {
                onChange({
                    ...selectedParts,
                    [attribute]: new Set([...Array.from(selectionContainer), value]),
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
    selectedParts: SelectedParts
    onChange: (s: SelectedParts) => void
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
}: {
    element: ElementType
    isDeepestChild: boolean
    onChange: (selector: string) => void
    readonly: boolean
    indent: string
    highlight?: boolean
}): JSX.Element {
    const [selectedParts, setSelectedParts] = useState<SelectedParts>({})

    useEffect(() => {
        const attributeSelectors = Object.entries(selectedParts).reduce((acc, [key, value]) => {
            if (!!value && key !== 'tag' && key !== 'text') {
                if (key === 'class') {
                    if (value instanceof Set) {
                        acc.push(`.${Array.from(value).join('.')}`)
                    } else {
                        throw new Error(`Was expecting a set here. Attribute: ${key} has a string value: ${value}`)
                    }
                } else {
                    if (value instanceof Set) {
                        throw new Error(
                            `Not expecting a set here. Attribute: ${key} has a set value: ${Array.from(value).join(
                                ', '
                            )}`
                        )
                    } else {
                        acc.push(`[${key}="${value}"]`)
                    }
                }
            }
            return acc
        }, [] as string[])

        const tagSelector = selectedParts.tag ? selectedParts.tag : ''
        const idSelector = selectedParts.id ? `[id="${selectedParts.id}"]` : ''
        const builtSelector = `${tagSelector}${idSelector}${attributeSelectors.join('')}`

        onChange(builtSelector)
    }, [selectedParts])

    return (
        <pre
            className={clsx(
                'p-0 m-0 rounded whitespace-pre-wrap break-all text-white text-sm',
                isDeepestChild && highlight ? 'bg-primary-light' : 'bg-transparent'
            )}
        >
            {indent}
            &lt;
            <TagPart
                tagName={element.tag_name}
                selectedParts={selectedParts}
                readonly={readonly}
                onChange={setSelectedParts}
            />
            {element.attr_id && ' '}
            <IdPart
                id={element.attr_id}
                selectedParts={selectedParts}
                readonly={readonly}
                onChange={setSelectedParts}
            />
            {Object.entries(element.attributes ?? {})
                .filter(([key]) => key !== 'style')
                .map(([key, value]) => {
                    const attrName: string = key.replace('attr__', '')
                    return (
                        <AttributePart
                            key={`${indent.length}-${element.tag_name}-${attrName}-${value}`}
                            attribute={attrName}
                            values={value.split(' ')}
                            selectedParts={selectedParts}
                            onChange={setSelectedParts}
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
