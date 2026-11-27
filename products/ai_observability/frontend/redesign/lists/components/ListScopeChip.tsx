import { IconX } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import type { ListScope, ListScopeKind } from '../listScopes'

const PREFIX: Record<ListScopeKind, string> = { person: 'Person', error: 'Error', tool: 'Tool' }

export interface ListScopeChipProps {
    scope: ListScope
    /** The text after the prefix, such as the person's name or the error message. */
    label: string
    onClear: () => void
}

export function ListScopeChip({ scope, label, onClear }: ListScopeChipProps): JSX.Element {
    const prefix = PREFIX[scope.kind]
    return (
        // pinned: autocapture dashboards and tests select the chip and its clear button by these values
        <LemonTag weight="normal" className="max-w-96 min-w-0" data-attr="list-scope-chip">
            <span className="shrink-0 text-secondary">{prefix}:</span>
            {/* A person's label can name an end user, and an error message can quote one, so autocapture must not read
                any label. The title sits here, not on the tag, because autocapture records the attributes of a clicked
                element's ancestors. */}
            <span className="ph-no-capture min-w-0 truncate" title={scope.value}>
                {label}
            </span>
            <LemonButton
                size="xsmall"
                noPadding
                icon={<IconX />}
                onClick={onClear}
                tooltip={`Remove ${prefix.toLowerCase()} filter`}
                aria-label={`Remove ${prefix.toLowerCase()} filter`}
                data-attr="list-scope-chip-clear"
            />
        </LemonTag>
    )
}
