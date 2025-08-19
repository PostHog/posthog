import { useActions } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { InstanceSetting } from '~/types'

import { asyncMigrationsLogic } from './asyncMigrationsLogic'

export function SettingUpdateField({ setting }: { setting: InstanceSetting }): JSX.Element {
    const { updateSetting } = useActions(asyncMigrationsLogic)

    const [inputValue, setInputValue] = useState<string>(String(setting.value))

    return (
        <div key={setting.key}>
            <h4>{setting.key}</h4>
            <p>{setting.description}</p>
            <div className="flex deprecated-space-x-2">
                <div className="w-1/3">
                    <LemonInput value={inputValue} onChange={setInputValue} />
                </div>
                <div>
                    <LemonButton
                        type="secondary"
                        disabledReason={String(setting.value) === inputValue && 'Edit the value to save it'}
                        onClick={() => updateSetting(setting.key, inputValue)}
                    >
                        Update
                    </LemonButton>
                </div>
            </div>
            <LemonDivider />
        </div>
    )
}
