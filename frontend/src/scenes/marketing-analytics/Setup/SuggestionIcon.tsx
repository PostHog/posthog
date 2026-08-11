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

/** One ad platform's logo, or null when there isn't one to show.
 *
 * A hook rather than a component so callers can branch on its absence — a component
 * returning null still gives the caller a truthy element, which is exactly the bug
 * this shape avoids.
 *
 * It also adds the one guard every caller here needs. `SourceIcon` renders a bare
 * `LemonSkeleton` while `availableSources` is null, and null is *also* the terminal
 * state when the wizard endpoint 403s — so a user without warehouse access would get
 * a skeleton sitting there forever. Asking the catalogue first means no logo simply
 * means no logo.
 *
 * `disableTooltip` because SourceIcon's default wraps the image in a link to its docs
 * page. A nested clickable inside a row that already has a primary action is a
 * misclick waiting to happen, and it navigates out of a checklist mid-task.
 */
export function usePlatformLogo(integration: string | null): JSX.Element | null {
    const { availableSources } = useValues(availableSourcesLogic)

    if (!integration || !availableSources?.[integration]) {
        return null
    }
    return <SourceIcon type={integration} size="small" disableTooltip />
}

/** The leading visual for a suggestion row.
 *
 * Shows the ad platform's logo when the finding belongs to exactly one platform —
 * which is most of them, and is the fastest way to scan a list for "what's wrong
 * with Meta". Severity survives as a dot on the corner of the logo rather than being
 * dropped: it's the only thing on the row that says whether this blocks a metric or
 * merely improves it.
 *
 * Falls back to the plain severity icon whenever there's no single platform to name —
 * a collapsed group, a conversion goal, untagged traffic from everywhere.
 */
export function SuggestionIcon({ suggestion }: { suggestion: Suggestion }): JSX.Element {
    const logo = usePlatformLogo(suggestion.integration)

    // A fixed-width slot, always, logo or not. Sizing the leading element to its
    // content indented every titled row differently depending on whether its platform
    // happened to resolve a logo, which turned a ranked list into a ragged one — and
    // made the same list re-flow the moment an icon 404'd.
    //
    // `SourceIcon`'s `small` is 30px; the slot matches so the logo sits flush and the
    // glyph centres in the same column.
    return (
        <Tooltip
            title={
                suggestion.integration
                    ? `${suggestion.integration} · ${SEVERITY_LABEL[suggestion.severity]}`
                    : SEVERITY_LABEL[suggestion.severity]
            }
        >
            {/* 30px exactly, not the nearest `size-8`: rounding to 32 would leave the
                logo a pixel off-centre in every row that has one. */}
            <span
                className="relative shrink-0 flex items-center justify-center cursor-help size-[30px]"
                data-attr="suggestion-icon"
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
