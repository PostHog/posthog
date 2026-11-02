import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconRefresh, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { sourceMapsStepLogic } from './sourceMapsStepLogic'

export function SourceMapStatus(): JSX.Element {
    const { lastSymbolSet, lastSymbolSetLoading } = useValues(sourceMapsStepLogic)
    const { loadLastSymbolSet } = useActions(sourceMapsStepLogic)

    return (
        <div className="mt-6 p-4 border rounded bg-bg-light">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    {lastSymbolSetLoading ? (
                        <>
                            <div className="animate-pulse w-6 h-6 rounded-full bg-border" />
                            <div>
                                <div className="font-semibold">Looking for source maps...</div>
                                <div className="text-sm text-muted">Last updated: N/A</div>
                            </div>
                        </>
                    ) : lastSymbolSet ? (
                        <>
                            <IconCheckCircle className="text-success text-2xl" />
                            <div>
                                <div className="font-semibold">Source maps uploaded</div>
                                <div className="text-sm text-muted">
                                    Last uploaded <TZLabel time={lastSymbolSet.created_at} />
                                </div>
                            </div>
                        </>
                    ) : (
                        <>
                            <IconWarning className="text-warning text-2xl" />
                            <div>
                                <div className="font-semibold">No source maps uploaded yet</div>
                                <div className="text-sm text-muted">
                                    Upload source maps to see readable stack traces
                                </div>
                            </div>
                        </>
                    )}
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconRefresh />}
                    onClick={() => loadLastSymbolSet()}
                    loading={lastSymbolSetLoading}
                >
                    Refresh
                </LemonButton>
            </div>
        </div>
    )
}
