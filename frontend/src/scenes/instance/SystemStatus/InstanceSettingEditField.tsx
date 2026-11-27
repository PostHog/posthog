import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { InstanceSetting } from '~/types'

import { systemStatusLogic } from './systemStatusLogic'

function toInputValue(value: InstanceSetting['value']): string {
    return Array.isArray(value) ? value.join(', ') : String(value ?? '')
}

export function InstanceSettingEditField({ setting }: { setting: InstanceSetting }): JSX.Element {
    const { instanceSettingUpdating } = useValues(systemStatusLogic)
    const { updateInstanceSetting } = useActions(systemStatusLogic)
    const [inputValue, setInputValue] = useState(toInputValue(setting.value))

    return (
        <div className="flex gap-2 items-center">
            <LemonInput size="small" className="min-w-40" value={inputValue} onChange={setInputValue} />
            <LemonButton
                type="secondary"
                size="small"
                loading={instanceSettingUpdating === setting.key}
                disabledReason={
                    instanceSettingUpdating && instanceSettingUpdating !== setting.key
                        ? 'Another setting is saving'
                        : inputValue === toInputValue(setting.value)
                          ? 'Edit the value to save it'
                          : undefined
                }
                onClick={() => updateInstanceSetting(setting.key, inputValue)}
                data-attr="instance-setting-save"
            >
                Save
            </LemonButton>
        </div>
    )
}
