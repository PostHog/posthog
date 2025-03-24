import { useEffect, useRef, useState } from 'react'

import { Node } from '~/queries/schema/schema-general'

export function useDebouncedQuery<T extends Node = Node, V extends string = string>(
    query: T,
    setQuery: ((query: T) => void) | undefined,
    getValueFromQuery: (query: T) => V,
    getModifiedQuery: (query: T, value: V) => T,
    timeoutMs: number = 300
): { value: V; onChange: (value: V) => void } {
    const propsValue: V = getValueFromQuery(query)
    const [localValue, setLocalValue] = useState(propsValue)

    // keep a ref to the latest query, so we don't override any other changes while waiting
    const queryRef = useRef(query)
    useEffect(() => {
        queryRef.current = query
    }, [query])

    const timeoutRef = useRef<number>()
    const onChange = (newValue: V): void => {
        setLocalValue(newValue)
        timeoutRef.current && clearTimeout(timeoutRef.current)
        timeoutRef.current = window.setTimeout(() => {
            setQuery?.(getModifiedQuery(queryRef.current, newValue))
        }, timeoutMs)
    }
    return { value: localValue, onChange }
}
