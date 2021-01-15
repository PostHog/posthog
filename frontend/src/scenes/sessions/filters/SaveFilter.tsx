import React, { useState } from 'react'
import { Button, Input } from 'antd'

interface Props {
    onSubmit: (name: string) => void
}

export function SaveFilter({ onSubmit }: Props): JSX.Element {
    const [name, setName] = useState('')

    return (
        <div style={{ maxWidth: 350 }} className="mb">
            <form
                onSubmit={(e): void => {
                    e.preventDefault()
                    onSubmit(name)
                }}
            >
                <div className="mb">
                    <Input
                        required
                        autoFocus
                        placeholder="Session filter name"
                        value={name}
                        data-attr="sessions-filter.name"
                        onChange={(e) => setName(e.target.value)}
                    />
                </div>
                <div className="mt">
                    <Button
                        type="primary"
                        htmlType="submit"
                        disabled={name.length < 2}
                        data-attr="save-sessions-filter"
                        style={{ marginTop: '1rem' }}
                    >
                        Save filter
                    </Button>
                </div>
            </form>
        </div>
    )
}
