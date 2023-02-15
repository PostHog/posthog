import { ElementType } from '~/types'
import clsx from 'clsx'
import { useEffect, useState } from 'react'
import './SelectableElement.scss'
type SelectedParts = Record<string, string | undefined>

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
    const htmlElementsSelector = clsx('SelectableElement decoration-primary-highlight', !readonly && 'cursor-pointer')
    const isSelected = !!selectedParts.tag
    return (
        <span
            onClick={(e) => {
                e.stopPropagation()
                return onChange({ ...selectedParts, tag: isSelected ? undefined : tagName })
            }}
            className={clsx(htmlElementsSelector, isSelected ? 'SelectableElement__selected' : hoverSelector)}
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
    const htmlElementsSelector = clsx('SelectableElement decoration-primary-highlight', !readonly && 'cursor-pointer')
    const isSelected = !!selectedParts.id

    return !!id ? (
        <span
            onClick={(e) => {
                e.stopPropagation()
                return onChange({ ...selectedParts, id: isSelected ? undefined : id })
            }}
            className={clsx(htmlElementsSelector, isSelected ? 'SelectableElement__selected' : hoverSelector)}
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
}: {
    attribute: string
    value: string
    selectedParts: SelectedParts
    onChange: (s: SelectedParts) => void
    readonly: boolean
}): JSX.Element {
    const hoverSelector = readonly ? '' : 'hover:underline'
    const htmlElementsSelector = clsx('SelectableElement decoration-primary-highlight', !readonly && 'cursor-pointer')
    const selectedPartForAttribute = selectedParts[attribute]
    const isSelected = selectedPartForAttribute === value

    return (
        <>
            <span
                onClick={(e) => {
                    e.stopPropagation()
                    onChange({ ...selectedParts, [attribute]: isSelected ? undefined : value })
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
}: {
    attribute: string
    values: string[]
    selectedParts: SelectedParts
    onChange: (s: SelectedParts) => void
    readonly: boolean
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
            /**
             * TODO support matching on multiple values for the same class attribute
             * e.g. ".TopBar .w-full.universal-search-button"
             */
            if (!!value && key !== 'tag' && key !== 'text') {
                if (key === 'class') {
                    acc.push(`.${value}`)
                } else {
                    acc.push(`[${key}="${value}"]`)
                }
            }
            return acc
        }, [] as string[])

        const tagSelector = selectedParts.tag ? selectedParts.tag : ''
        const idSelector = selectedParts.id ? `[id="${selectedParts.id}"]` : ''
        const textSelector = selectedParts.text ? `[text="${selectedParts.text}"]` : ''
        const builtSelector = `${tagSelector}${idSelector}${attributeSelectors.join('')}${textSelector}`

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
            {Object.entries(element.attributes ?? {}).map(([key, value]) => {
                const attrName: string = key.replace('attr__', '')
                return (
                    <AttributePart
                        key={`${indent.length}-${element.tag_name}-${attrName}-${value}`}
                        attribute={attrName}
                        values={value.split(' ')}
                        selectedParts={selectedParts}
                        onChange={setSelectedParts}
                        readonly={readonly}
                    />
                )
            })}
            &gt;
            {element.text}
            {isDeepestChild && <span>&lt;/{element.tag_name}&gt;</span>}
        </pre>
    )
}
