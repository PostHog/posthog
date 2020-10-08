import React, { useRef, useEffect, useCallback } from 'react'
import { Input, Row } from 'antd'

interface Props {
    input: string
    setInput: (input: string) => void
    onClose: () => void
}
export function CommandSearch({ input, setInput, onClose }: Props): JSX.Element {
    const inputRef = useRef<Input | null>(null)

    const handle = useCallback(
        (event: KeyboardEvent): void => {
            if (event.key === 'Escape') {
                event.preventDefault()
                // If 'esc' is pressed once, delete text. If pressed twice, close window
                if (input) setInput('')
                else onClose()
            } else if (event.key === 'k' && (event.ctrlKey || event.metaKey)) onClose()
        },
        [input, setInput]
    )

    // focus on text input by default
    useEffect((): void => {
        inputRef.current?.focus()
    }, [])

    return (
        <Row
            style={{
                display: 'flex',
                flexDirection: 'row',
                justifyContent: 'center',
                alignItems: 'center',
                width: '100%',
                paddingTop: 20,
                paddingLeft: 25,
                paddingRight: 25,
            }}
        >
            <Input
                ref={inputRef}
                value={input}
                onKeyDown={handle}
                onChange={(e): void => setInput(e.target.value)}
                size="large"
                placeholder="What would you like to do?"
                bordered={false}
                style={{ color: 'rgba(255, 255, 255, 0.9)' }}
            ></Input>
        </Row>
    )
}
