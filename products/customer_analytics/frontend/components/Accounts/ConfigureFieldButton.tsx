import { useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import type { AccountConfigField } from './accountLinksLogic'

interface ConfigureFieldButtonProps {
    field: AccountConfigField
    loading: boolean
    onSave: (value: string) => void
}

export function ConfigureFieldButton({ field, loading, onSave }: ConfigureFieldButtonProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const [value, setValue] = useState('')

    const close = (): void => {
        setOpen(false)
        setValue('')
    }

    const submit = (): void => {
        if (!value.trim()) {
            return
        }
        onSave(value)
    }

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={open}
            onVisibilityChange={(visible) => (visible ? setOpen(true) : close())}
            showArrow
            overlay={
                <div className="flex flex-col gap-1 w-64">
                    <span className="text-xs font-semibold text-secondary">{field.label}</span>
                    <LemonInput
                        type="text"
                        size="small"
                        value={value}
                        onChange={setValue}
                        placeholder={field.placeholder}
                        autoFocus
                        onPressEnter={submit}
                    />
                    <LemonDivider className="my-1" />
                    <div className="flex flex-row gap-2 justify-end">
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            onClick={close}
                            sideIcon={<KeyboardShortcut escape />}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            size="xsmall"
                            type="primary"
                            onClick={submit}
                            loading={loading}
                            disabledReason={loading ? 'Saving…' : !value.trim() ? 'Enter a value' : undefined}
                            sideIcon={<KeyboardShortcut enter />}
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={<IconGear />}
                loading={loading}
                tooltip={field.label}
                data-attr={`configure-${field.key}`}
                onClick={() => setOpen(true)}
            />
        </LemonDropdown>
    )
}
