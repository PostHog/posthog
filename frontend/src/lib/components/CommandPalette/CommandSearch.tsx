import React from 'react'
import { Input, Row } from 'antd'
import { useState } from 'react'
import { useRef } from 'react'
import { useEffect } from 'react'

interface Props {
    onClose: () => void
}
export function CommandSearch({ onClose }: Props): JSX.Element {
    const ref = useRef()
    const [input, setInput] = useState('')
    const [isSequence, setIsSequence] = useState(false)

    const handle = (event: KeyboardEvent): void => {
        if (event.key === 'Escape') {
            event.preventDefault()

            // if 'esc' is pressed once, delete text. If pressed twice, close window
            if (input) setInput('')
            else onClose()
        } else {
            if (event.key === 'k' && isSequence) onClose()
            else if (event.key === 'Control' || event.key === 'Meta') setIsSequence(true)
            else setIsSequence(false)
        }
    }

    // focus on text input by default
    useEffect((): void => {
        ref.current?.focus()
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
                ref={ref}
                value={input}
                onKeyDown={handle}
                onChange={(e): void => setInput(e.target.value)}
                size="large"
                placeholder="what would you like to do?"
                bordered={false}
                style={{ color: 'rgba(255, 255, 255, 0.9)' }}
            ></Input>
        </Row>
    )
}
