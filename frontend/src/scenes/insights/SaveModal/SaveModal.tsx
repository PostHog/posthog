import React, { useState } from 'react'
import { Modal, Button, Input } from 'antd'

interface SaveChartModalProps {
    visible: boolean
    onCancel: () => void
    onSubmit: (input: string) => void
    title: string
    prompt: string
    textLabel: string
    textPlaceholder?: string
}

const SaveModal: React.FC<SaveChartModalProps> = (props) => {
    const { visible, onCancel, onSubmit, title, prompt, textLabel, textPlaceholder } = props
    const [input, setInput] = useState<string>('')

    function _onCancel(): void {
        setInput('')
        onCancel()
    }

    function _onSubmit(input: string): void {
        setInput('')
        onSubmit(input)
    }

    return (
        <Modal
            visible={visible}
            footer={
                <Button type="primary" onClick={(): void => _onSubmit(input)}>
                    Save
                </Button>
            }
            onCancel={_onCancel}
        >
            <div data-attr="save-modal">
                <h2>{title}</h2>
                <label>{prompt}</label>
                <Input
                    name={textLabel}
                    required
                    type="text"
                    placeholder={textPlaceholder}
                    value={input}
                    onChange={(e): void => setInput(e.target.value)}
                />
            </div>
        </Modal>
    )
}

export default SaveModal
