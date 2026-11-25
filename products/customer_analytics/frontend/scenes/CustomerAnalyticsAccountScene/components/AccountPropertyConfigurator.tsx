import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonModal } from '@posthog/lemon-ui'

import { AccountPropertySelection } from './AccountPropertySelection'
import { AccountPropertyDefaultOption, AccountPropertyOption } from './accountPropertyTypes'

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
    resetOptions?: AccountPropertyDefaultOption[]
    onReset?: (option: AccountPropertyDefaultOption) => void
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
    resetOptions,
    onReset,
}: AccountPropertyConfiguratorProps): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            title={title}
            onClose={onCancel}
            footer={
                <>
                    {resetOptions && resetOptions.length > 0 ? (
                        <div className="mr-auto">
                            <LemonMenu
                                items={resetOptions.map((option) => ({
                                    key: option.key,
                                    label: option.label,
                                    onClick: () => {
                                        if (!saving) {
                                            onReset?.(option)
                                        }
                                    },
                                    'data-attr': `account-pinned-properties-reset-${option.key}`,
                                }))}
                            >
                                <LemonButton
                                    type="secondary"
                                    sideIcon={<IconChevronDown />}
                                    disabledReason={saving ? 'Saving' : undefined}
                                    data-attr="account-pinned-properties-reset"
                                >
                                    Reset to default
                                </LemonButton>
                            </LemonMenu>
                        </div>
                    ) : null}
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
