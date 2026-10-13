import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { FlagRow, extensionPageToolsLogic } from './extensionPageToolsLogic'

function FlagOverrideControl({ row }: { row: FlagRow }): JSX.Element {
    const { pageFlagsLoading } = useValues(extensionPageToolsLogic)
    const { setFlagOverride } = useActions(extensionPageToolsLogic)
    const current = row.override ?? row.value

    if (row.variants.length > 0) {
        return (
            <LemonSelect
                size="xsmall"
                value={typeof current === 'string' ? current : null}
                options={row.variants.map((variant) => ({ value: variant, label: variant }))}
                disabledReason={pageFlagsLoading ? 'Applying override…' : undefined}
                onChange={(variant) => setFlagOverride(row.key, variant)}
                data-attr="toolbar-extension-flag-variant"
            />
        )
    }
    return (
        <LemonSwitch
            checked={current === true}
            disabledReason={pageFlagsLoading ? 'Applying override…' : undefined}
            onChange={(checked) => setFlagOverride(row.key, checked)}
            data-attr="toolbar-extension-flag-toggle"
        />
    )
}

export function ExtensionFlagOverrides(): JSX.Element {
    const { flagRows, pageFlags, pageFlagsLoading, userFlags, userFlagsLoading } = useValues(extensionPageToolsLogic)
    const { setFlagOverride, clearFlagOverrides } = useActions(extensionPageToolsLogic)
    const overrideCount = Object.keys(pageFlags?.overrides ?? {}).length

    if ((userFlagsLoading && !userFlags) || (pageFlagsLoading && !pageFlags)) {
        return (
            <div className="flex items-center gap-2 text-secondary text-xs">
                <Spinner />
                Loading feature flags…
            </div>
        )
    }
    if (!pageFlags) {
        return <div className="text-danger text-xs">Couldn't read flag overrides on this page.</div>
    }
    if (!pageFlags.available) {
        return (
            <div className="text-secondary text-xs">
                Flag overrides need posthog-js on <code>window.posthog</code>, and this page doesn't have it.
            </div>
        )
    }
    if (!userFlags) {
        return <div className="text-danger text-xs">Couldn't load feature flags. Open the popup again to retry.</div>
    }

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold">Feature flags</span>
                <LemonButton
                    size="xsmall"
                    disabledReason={overrideCount === 0 ? 'No overrides on this page' : null}
                    onClick={clearFlagOverrides}
                    data-attr="toolbar-extension-clear-flag-overrides"
                >
                    Reset overrides
                </LemonButton>
            </div>
            {flagRows.length === 0 ? (
                <div className="text-secondary text-xs">This project has no active feature flags.</div>
            ) : (
                <div className="flex flex-col max-h-48 overflow-y-auto">
                    {flagRows.map((row) => (
                        <div key={row.key} className="flex items-center gap-2 py-0.5">
                            <span className="flex-1 truncate text-xs" title={row.key} translate="no">
                                {row.key}
                            </span>
                            {row.override !== undefined && (
                                <LemonButton
                                    size="xsmall"
                                    tooltip="Remove override"
                                    onClick={() => setFlagOverride(row.key, null)}
                                    data-attr="toolbar-extension-remove-flag-override"
                                >
                                    Overridden
                                </LemonButton>
                            )}
                            <FlagOverrideControl row={row} />
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
