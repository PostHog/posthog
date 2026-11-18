import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { AccountPropertySelection } from './AccountPropertySelection'
import { AccountPropertyOption } from './accountPropertyTypes'

export interface AccountPropertyConfiguratorProps {
    isOpen: boolean
    options: AccountPropertyOption[]
    pinnedPropertyKeys: string[]
    saving?: boolean
    onChange: (pinnedPropertyKeys: string[]) => void
    onSave: (pinnedPropertyKeys: string[]) => void
    onCancel: () => void
    saveDisabledReason?: string
    title?: string
}

export function AccountPropertyConfigurator({
    isOpen,
    options,
    pinnedPropertyKeys,
    saving = false,
    onChange,
    onSave,
    onCancel,
    saveDisabledReason,
    title = 'Pin properties',
}: AccountPropertyConfiguratorProps): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            title={title}
            onClose={onCancel}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onCancel} data-attr="account-pinned-properties-cancel">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => onSave(pinnedPropertyKeys)}
                        loading={saving}
                        disabledReason={saveDisabledReason}
                        data-attr="account-pinned-properties-save"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="min-w-80">
                <AccountPropertySelection
                    options={options}
                    selectedKeys={pinnedPropertyKeys}
                    onChange={onChange}
                    saving={saving}
                />
            </div>
        </LemonModal>
    )
}
