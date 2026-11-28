import { IconSparkles, IconWarning } from '@posthog/icons'
import { Button } from '@posthog/quill'

import {
    FixErrorButtonSource,
    useFixErrorButtonState,
} from 'scenes/data-warehouse/editor/components/useFixErrorButtonState'

/**
 * Asks PostHog AI to fix the query's error. On the toolbar it only shows while there is an error to
 * fix, since fewer than 4% of editor users ever press it.
 */
export function QuillFixErrorButton({
    source,
    label,
    hideWithoutError = false,
}: {
    source: FixErrorButtonSource
    label?: string
    hideWithoutError?: boolean
}): JSX.Element | null {
    const {
        queryError,
        loading,
        failed,
        disabledReason,
        label: stateLabel,
        fix,
    } = useFixErrorButtonState(source, label)

    if (hideWithoutError && !queryError && !loading) {
        return null
    }

    return (
        <Button
            variant="outline"
            onClick={fix}
            loading={loading}
            disabledReason={disabledReason}
            data-attr="sql-editor-fix-error-button"
        >
            {failed ? <IconWarning className="text-warning-foreground" /> : <IconSparkles />}
            {stateLabel}
        </Button>
    )
}
