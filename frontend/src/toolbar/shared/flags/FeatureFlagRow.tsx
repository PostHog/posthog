import clsx from 'clsx'

import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Link } from 'lib/lemon-ui/Link'

import type { FlagInfo } from './flagInfo'

export interface FeatureFlagRowProps {
    flag: FlagInfo
    flagUrl: string
    /** `null` while the payload editor is closed. */
    payloadDraft: string | null
    payloadError: string | null
    /** Disables every change, for example while the page applies the last one. */
    disabledReason: string | null
    onSetOverride: (value: string | boolean) => void
    onRemoveOverride: () => void
    onOpenPayloadEditor: (initialDraft: string) => void
    onPayloadDraftChange: (draft: string) => void
    onSavePayload: () => void
    onClosePayloadEditor: () => void
    /** pinned: each form's `data-attr` values start with its own prefix */
    dataAttrPrefix: string
}

export function FeatureFlagRow({
    flag,
    flagUrl,
    payloadDraft,
    payloadError,
    disabledReason,
    onSetOverride,
    onRemoveOverride,
    onOpenPayloadEditor,
    onPayloadDraftChange,
    onSavePayload,
    onClosePayloadEditor,
    dataAttrPrefix,
}: FeatureFlagRowProps): JSX.Element {
    const { key, value, currentValue, hasOverride, variants, payloadOverride } = flag
    const hasPayloadOverride = payloadOverride !== null && payloadOverride !== undefined

    // Choosing the value PostHog evaluates removes the override instead of pinning that value.
    const choose = (newValue: string | boolean): void => {
        if (newValue === value && hasOverride) {
            onRemoveOverride()
        } else {
            onSetOverride(newValue)
        }
    }

    return (
        <div className={clsx('flex flex-col gap-1 rounded px-2 py-1', hasOverride && 'bg-fill-primary')}>
            <div className="flex items-center gap-2">
                <Link className="flex-1 min-w-0 truncate font-medium" to={flagUrl} target="_blank" subtle>
                    <span translate="no">{key}</span> <IconOpenInNew />
                </Link>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={() =>
                        onOpenPayloadEditor(hasPayloadOverride ? JSON.stringify(payloadOverride, null, 2) : '')
                    }
                    disabledReason={disabledReason ?? (currentValue ? null : 'Turn the flag on to edit its payload')}
                    data-attr={`${dataAttrPrefix}-edit-payload`}
                >
                    Edit payload
                </LemonButton>
                <LemonSwitch
                    checked={!!currentValue}
                    disabledReason={disabledReason}
                    onChange={(checked) => choose(variants.length > 0 && checked ? variants[0].key : checked)}
                    data-attr={`${dataAttrPrefix}-toggle`}
                />
            </div>
            <AnimatedCollapsible collapsed={!currentValue}>
                <div className="flex flex-col gap-1">
                    {variants.length > 0 ? (
                        <LemonRadio
                            className="pl-4"
                            value={typeof currentValue === 'string' ? currentValue : undefined}
                            options={variants.map((variant) => ({
                                label: `${variant.key}${variant.name ? ` - ${variant.name}` : ''}${
                                    variant.rolloutPercentage !== null ? ` (${variant.rolloutPercentage}%)` : ''
                                }`,
                                value: variant.key,
                                disabledReason: disabledReason ?? undefined,
                            }))}
                            onChange={choose}
                        />
                    ) : null}
                    {payloadDraft !== null ? (
                        <div className="flex items-start gap-2">
                            <LemonTextArea
                                className={clsx('flex-1 font-mono text-xs', payloadError && 'border-danger')}
                                value={payloadDraft}
                                onChange={onPayloadDraftChange}
                                placeholder='For example: "A string", 2500, {"key": "value"}'
                                minRows={2}
                            />
                            <div className="flex flex-col gap-1">
                                <LemonButton
                                    size="xsmall"
                                    type="primary"
                                    center
                                    disabledReason={disabledReason}
                                    onClick={onSavePayload}
                                    data-attr={`${dataAttrPrefix}-save-payload`}
                                >
                                    Save
                                </LemonButton>
                                <LemonButton size="xsmall" center onClick={onClosePayloadEditor}>
                                    Cancel
                                </LemonButton>
                            </div>
                        </div>
                    ) : hasPayloadOverride ? (
                        <div className="truncate font-mono text-xs text-secondary" translate="no">
                            {JSON.stringify(payloadOverride)}
                        </div>
                    ) : null}
                    {payloadError ? <div className="text-xs text-danger">{payloadError}</div> : null}
                </div>
            </AnimatedCollapsible>
        </div>
    )
}
