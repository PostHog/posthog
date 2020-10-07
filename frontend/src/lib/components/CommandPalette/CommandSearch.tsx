import React from 'react'
import { Input, Row } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { useState } from 'react'
import { useRef } from 'react'
import { useEffect } from 'react'

interface Props {
    onClose: () => void
}
export function CommandSearch({ onClose }: Props): JSX.Element {
    const ref = useRef()
    const [input, setInput] = useState('')

    const handle = (event: KeyboardEvent): void => {
        if (event.key === 'Escape') {
            event.preventDefault()

            // if 'esc' is pressed once, delete text. If pressed twice, close window
            if (input) setInput('')
            else onClose()
        } else if (event.key === 'k' && (event.ctrlKey || event.metaKey)) onClose()
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
                placeholder="What would you like to do? (e.g. Go to default dashboard)"
                prefix={<SearchOutlined style={{ marginRight: 10 }}></SearchOutlined>}
                bordered={false}
            ></Input>
        </Row>
    )
}
