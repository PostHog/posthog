import React, { useState } from 'react'
import { Input, Modal } from 'antd'

interface Props {
    onOk: (title: string) => void
    onCancel: () => void
    visible: boolean
}

export function SaveCohortModal({ onOk, onCancel, visible }: Props): JSX.Element {
    const [cohortTitle, setCohortTitle] = useState('')
    return (
        <Modal
            title={`New Cohort`}
            okText={'Save'}
            cancelText="Cancel"
            onOk={() => {
                onOk(cohortTitle)
                setCohortTitle('')
            }}
            onCancel={onCancel}
            visible={visible}
        >
            <div className="mb-4">
                <Input
                    required
                    autoFocus
                    placeholder="Cohort name..."
                    value={cohortTitle}
                    data-attr="cohort-name"
                    onChange={(e) => setCohortTitle(e.target.value)}
                />
            </div>
        </Modal>
    )
}
