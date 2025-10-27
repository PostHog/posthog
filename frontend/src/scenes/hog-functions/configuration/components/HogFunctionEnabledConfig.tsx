import { useActions, useValues } from 'kea'

import { LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { HogFunctionStatusIndicator } from 'scenes/hog-functions/misc/HogFunctionStatusIndicator'
import { HogFunctionStatusTag } from 'scenes/hog-functions/misc/HogFunctionStatusTag'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'

export function HogFunctionEnabledConfig(): JSX.Element {
    const { configuration, loading, hogFunction, template } = useValues(hogFunctionConfigurationLogic)
    const { setConfigurationValue } = useActions(hogFunctionConfigurationLogic)

    return (
        <div className="flex items-center gap-2">
            {template && <HogFunctionStatusTag status={template.status} />}
            {hogFunction ? (
                <HogFunctionStatusIndicator hogFunction={hogFunction} />
            ) : (
                <LemonTag type={configuration.enabled ? 'success' : 'default'}>
                    {configuration.enabled ? 'Start enabled' : 'Start paused'}
                </LemonTag>
            )}
            <LemonSwitch
                onChange={() => setConfigurationValue('enabled', !configuration.enabled)}
                checked={configuration.enabled}
                disabled={loading}
                tooltip={
                    <>
                        {configuration.enabled
                            ? 'Enabled. Events will be processed.'
                            : 'Disabled. Events will not be processed.'}
                    </>
                }
            />
        </div>
    )
}
