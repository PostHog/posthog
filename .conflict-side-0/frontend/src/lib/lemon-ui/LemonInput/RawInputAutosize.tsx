import { useMergeRefs } from '@floating-ui/react'
import clsx from 'clsx'
import React, { HTMLProps, useLayoutEffect, useRef, useState } from 'react'

interface RawInputAutosizeProps extends HTMLProps<HTMLInputElement> {
    wrapperClassName?: string
}

export const RawInputAutosize = React.forwardRef<HTMLInputElement, RawInputAutosizeProps>(function RawInputAutosize(
    { wrapperClassName, ...inputProps },
    ref
) {
    const [inputWidth, setInputWidth] = useState<number | string>(1)
    const [inputStyles, setInputStyles] = useState<CSSStyleDeclaration>()
    const sizerRef = useRef<HTMLDivElement>(null)
    const placeHolderSizerRef = useRef<HTMLDivElement>(null)
    const inputRef = useRef<HTMLInputElement>(null)
    const mergedRefs = useMergeRefs([ref, inputRef])

    useLayoutEffect(() => {
        if (inputRef.current) {
            setInputStyles(getComputedStyle(inputRef.current))
        }
    }, [inputRef.current])

    useLayoutEffect(() => {
        if (inputStyles) {
            if (sizerRef.current) {
                copyStyles(inputStyles, sizerRef.current)
            }
            if (placeHolderSizerRef.current) {
                copyStyles(inputStyles, placeHolderSizerRef.current)
            }
        }
    }, [inputStyles])

    useLayoutEffect(() => {
        if (!sizerRef.current || !placeHolderSizerRef.current) {
            return
        }
        let newInputWidth
        if (inputProps.placeholder && !inputProps.value) {
            newInputWidth = Math.max(sizerRef.current.scrollWidth, placeHolderSizerRef.current.scrollWidth) + 2
        } else {
            newInputWidth = sizerRef.current.scrollWidth + 2
        }
        if (newInputWidth !== inputWidth) {
            setInputWidth(newInputWidth)
        }
    }, [sizerRef.current, placeHolderSizerRef.current, inputProps.placeholder, inputProps.value, inputWidth])

    return (
        <div className={clsx('relative min-w-0', wrapperClassName)}>
            <input
                ref={mergedRefs}
                /* eslint-disable-next-line react/forbid-dom-props */
                style={{
                    boxSizing: 'content-box',
                    width: inputWidth,
                    maxWidth: '100%',
                }}
                {...inputProps}
            />
            {/* Intentionally using overflow-scroll below so that we can use these invisible elements for sizing */}
            <div ref={sizerRef} className="absolute top-0 left-0 h-0 overflow-scroll whitespace-pre invisible">
                {inputProps.value}
            </div>
            <div
                ref={placeHolderSizerRef}
                className="absolute top-0 left-0 h-0 overflow-scroll whitespace-pre invisible"
            >
                {inputProps.placeholder}
            </div>
        </div>
    )
})

function copyStyles(styles: CSSStyleDeclaration, node: HTMLDivElement): void {
    node.style.fontSize = styles.fontSize
    node.style.fontFamily = styles.fontFamily
    node.style.fontWeight = styles.fontWeight
    node.style.fontStyle = styles.fontStyle
    node.style.letterSpacing = styles.letterSpacing
    node.style.textTransform = styles.textTransform
}
