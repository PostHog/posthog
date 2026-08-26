import { useValues } from 'kea'

import { IconInfo, IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import type { Suggestion } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { availableSourcesLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/availableSourcesLogic'
import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

const SEVERITY_LABEL: Record<Suggestion['severity'], string> = {
    error: 'Blocking — a metric is unavailable or wrong until this is fixed',
    warning: 'Worth fixing — some data is missing or misattributed',
    info: 'Optional improvement',
}

const SEVERITY_DOT: Record<Suggestion['severity'], string> = {
    error: 'bg-danger',
    warning: 'bg-warning',
    info: 'bg-muted',
}

function SeverityGlyph({ severity }: { severity: Suggestion['severity'] }): JSX.Element {
    if (severity === 'info') {
        return <IconInfo className="text-secondary text-lg" />
    }
    return <IconWarning className={severity === 'error' ? 'text-danger text-lg' : 'text-warning text-lg'} />
}

/** Checking the catalogue first because `SourceIcon` renders a skeleton while
 * `availableSources` is null — which is also its terminal state when the wizard
 * endpoint 403s, so no warehouse access would mean a skeleton forever.
 *
 * `disableTooltip` because SourceIcon otherwise links to its docs page, and the row
 * already has a primary action.
 */
export function usePlatformLogo(integration: string | null): JSX.Element | null {
    const { availableSources } = useValues(availableSourcesLogic)

    if (!integration || !availableSources?.[integration]) {
        return null
    }
    return <SourceIcon type={integration} size="small" disableTooltip />
}

/** The platform logo with severity as a corner dot, falling back to the bare severity
 * glyph when the finding belongs to no single platform. */
export function SuggestionIcon({ suggestion }: { suggestion: Suggestion }): JSX.Element {
    const logo = usePlatformLogo(suggestion.integration)

    return (
        <Tooltip
            title={
                suggestion.integration
                    ? `${suggestion.integration} · ${SEVERITY_LABEL[suggestion.severity]}`
                    : SEVERITY_LABEL[suggestion.severity]
            }
        >
            {/* Fixed 30px — `SourceIcon`'s `small` — so rows don't go ragged when a logo
                is missing, and not `size-8` because 32 puts the logo off-centre. */}
            <span
                className="relative shrink-0 flex items-center justify-center cursor-help size-[30px]"
                data-attr="suggestion-icon"
                // Severity is otherwise colour and glyph shape only.
                tabIndex={0}
                aria-label={
                    suggestion.integration
                        ? `${suggestion.integration} · ${SEVERITY_LABEL[suggestion.severity]}`
                        : SEVERITY_LABEL[suggestion.severity]
                }
            >
                {logo ?? <SeverityGlyph severity={suggestion.severity} />}
                {logo && (
                    <span
                        className={`absolute -bottom-0.5 -right-0.5 size-2 rounded-full border border-bg-light ${
                            SEVERITY_DOT[suggestion.severity]
                        }`}
                    />
                )}
            </span>
        </Tooltip>
    )
}
