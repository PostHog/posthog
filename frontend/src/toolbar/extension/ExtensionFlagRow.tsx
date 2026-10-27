import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Link } from 'lib/lemon-ui/Link'

import { urls } from '~/toolbar/shared/urls'

import { extensionFlagsLogic } from './extensionFlagsLogic'
import { extensionPanelLogic } from './extensionPanelLogic'
import type { FlagInfo } from './pageToolbarBridge'

export function ExtensionFlagRow({ flag }: { flag: FlagInfo }): JSX.Element {
    const { draftPayloads, flagsState, mutationDisabledReason } = useValues(extensionFlagsLogic)
    const { setFlagOverride, removeFlagOverride, openPayloadEditor, closePayloadEditor, setDraftPayload, savePayload } =
        useActions(extensionFlagsLogic)
    const { projectUrl } = useValues(extensionPanelLogic)
    const { key, id, value, currentValue, hasOverride, variants, payloadOverride } = flag
    const draftPayload = draftPayloads[key]
    const payloadError = flagsState?.payloadErrors[key] ?? null

    // Matches the floating toolbar: choosing the value PostHog evaluates removes the override instead.
    const choose = (newValue: string | boolean): void => {
        if (newValue === value && hasOverride) {
            removeFlagOverride(key)
        } else {
            setFlagOverride(key, newValue)
        }
    }

    return (
        <div className={clsx('flex flex-col gap-1 rounded px-2 py-1', hasOverride && 'bg-fill-primary')}>
            <div className="flex items-center gap-2">
                <Link
                    className="flex-1 min-w-0 truncate font-medium"
                    to={projectUrl(id ? urls.featureFlag(id) : urls.featureFlags())}
                    target="_blank"
                    subtle
                >
                    <span translate="no">{key}</span> <IconOpenInNew />
                </Link>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={() =>
                        openPayloadEditor(key, payloadOverride !== null ? JSON.stringify(payloadOverride, null, 2) : '')
                    }
                    disabledReason={
                        mutationDisabledReason ?? (currentValue ? null : 'Turn the flag on to edit its payload')
                    }
                    data-attr="toolbar-extension-flag-edit-payload"
                >
                    Edit payload
                </LemonButton>
                <LemonSwitch
                    checked={!!currentValue}
                    disabledReason={mutationDisabledReason}
                    onChange={(checked) => choose(variants.length > 0 && checked ? variants[0].key : checked)}
                    data-attr="toolbar-extension-flag-toggle"
                />
            </div>
            {currentValue && variants.length > 0 ? (
                <LemonRadio
                    className="pl-4"
                    value={typeof currentValue === 'string' ? currentValue : undefined}
                    options={variants.map((variant) => ({
                        label: `${variant.key}${variant.name ? ` - ${variant.name}` : ''}${
                            variant.rolloutPercentage !== null ? ` (${variant.rolloutPercentage}%)` : ''
                        }`,
                        value: variant.key,
                        disabledReason: mutationDisabledReason ?? undefined,
                    }))}
                    onChange={choose}
                />
            ) : null}
            {draftPayload !== undefined ? (
                <div className="flex items-start gap-2">
                    <LemonTextArea
                        className={clsx('flex-1 font-mono text-xs', payloadError && 'border-danger')}
                        value={draftPayload}
                        onChange={(draft) => setDraftPayload(key, draft)}
                        placeholder='For example: "A string", 2500, {"key": "value"}'
                        minRows={2}
                    />
                    <div className="flex flex-col gap-1">
                        <LemonButton
                            size="xsmall"
                            type="primary"
                            center
                            disabledReason={mutationDisabledReason}
                            onClick={() => savePayload(key)}
                            data-attr="toolbar-extension-flag-save-payload"
                        >
                            Save
                        </LemonButton>
                        <LemonButton size="xsmall" center onClick={() => closePayloadEditor(key)}>
                            Cancel
                        </LemonButton>
                    </div>
                </div>
            ) : payloadOverride !== null ? (
                <div className="truncate font-mono text-xs text-secondary" translate="no">
                    {JSON.stringify(payloadOverride)}
                </div>
            ) : null}
            {payloadError ? <div className="text-xs text-danger">{payloadError}</div> : null}
        </div>
    )
}
