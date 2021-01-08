import React, { useState } from 'react'
import { Button, Input } from 'antd'

export function SaveFilter(): JSX.Element {
    const [name, setName] = useState('')

    return (
        <div style={{ maxWidth: 350 }} className="mb">
            <form
                onSubmit={(e): void => {
                    e.preventDefault()
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
                        disabled={name.length === 0}
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
