import { IconHourglass, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { formatLatencyMs } from '../../trace/components/formatStats'
import type { FacetKey, FacetOptions, FacetState } from '../facetFilters'
import { FacetSelect } from './FacetSelect'

export interface FacetFilterBarProps {
    facets: FacetState
    /** Null while the options load. */
    options: FacetOptions | null
    controls: readonly FacetKey[]
    onChange: (change: Partial<FacetState>) => void
    'data-attr': string
}

export function FacetFilterBar({
    facets,
    options,
    controls,
    onChange,
    'data-attr': dataAttr,
}: FacetFilterBarProps): JSX.Element {
    const shows = (facet: FacetKey): boolean => controls.includes(facet)
    const slowThreshold = options?.slowThresholdSeconds ?? null

    return (
        <>
            {shows('model') && (
                <FacetSelect
                    label="Model"
                    options={options?.models}
                    value={facets.models}
                    onChange={(models) => onChange({ models })}
                    data-attr={`${dataAttr}-facet-model`}
                />
            )}
            {shows('provider') && (
                <FacetSelect
                    label="Provider"
                    options={options?.providers}
                    value={facets.providers}
                    onChange={(providers) => onChange({ providers })}
                    data-attr={`${dataAttr}-facet-provider`}
                />
            )}
            {shows('tool') && (
                <FacetSelect
                    label="Tool"
                    options={options?.tools}
                    value={facets.tools}
                    onChange={(tools) => onChange({ tools })}
                    data-attr={`${dataAttr}-facet-tool`}
                />
            )}
            {shows('errors') && (
                <LemonButton
                    type="secondary"
                    size="small"
                    active={facets.errorsOnly}
                    aria-pressed={facets.errorsOnly}
                    icon={<IconWarning />}
                    onClick={() => onChange({ errorsOnly: !facets.errorsOnly })}
                    tooltip="Only events that ended in an error"
                    data-attr={`${dataAttr}-facet-errors`}
                >
                    Errors
                </LemonButton>
            )}
            {shows('slow') && (
                <LemonButton
                    type="secondary"
                    size="small"
                    active={facets.slow}
                    aria-pressed={facets.slow}
                    icon={<IconHourglass />}
                    onClick={() => onChange({ slow: !facets.slow })}
                    tooltip={
                        slowThreshold !== null
                            ? `Only generations slower than ${formatLatencyMs(slowThreshold * 1000)}, the p95 of the last 30 days`
                            : undefined
                    }
                    disabledReason={
                        !facets.slow && slowThreshold === null
                            ? options
                                ? 'No generation latency in the last 30 days'
                                : 'Loading'
                            : undefined
                    }
                    data-attr={`${dataAttr}-facet-slow`}
                >
                    Slow
                </LemonButton>
            )}
        </>
    )
}
