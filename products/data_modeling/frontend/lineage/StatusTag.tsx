import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { STATUS_TAG_SETTINGS, STATUS_TOOLTIPS } from './nodeStyles'

/** A run status, with the explanation attached wherever the word alone leaves a reader guessing. */
export function StatusTag({ status }: { status: string }): JSX.Element {
    const tag = <LemonTag type={STATUS_TAG_SETTINGS[status] ?? 'default'}>{status}</LemonTag>
    const explanation = STATUS_TOOLTIPS[status]
    return explanation ? <Tooltip title={explanation}>{tag}</Tooltip> : tag
}
