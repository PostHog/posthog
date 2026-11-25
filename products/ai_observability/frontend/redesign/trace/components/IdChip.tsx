import { LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

import { LabeledChipValue } from './LabeledChipValue'

const HEX_ID_PATTERN = /^[0-9a-f-]{16,}$/i

export interface IdChipProps {
    id: string
    /** What the id names, as the copied toast says it, like "trace ID". */
    description: string
    /** For an id a customer sets, such as a session id, which autocapture must not record. */
    isSensitive?: boolean
}

export function IdChip({ id, description, isSensitive = false }: IdChipProps): JSX.Element {
    return (
        <LemonTag weight="normal">
            <LabeledChipValue label="ID">
                <CopyToClipboardInline
                    explicitValue={id}
                    description={description}
                    isValueSensitive={isSensitive}
                    className="font-mono"
                    iconSize="xsmall"
                >
                    {HEX_ID_PATTERN.test(id) ? (
                        <span>{id.slice(0, 8)}</span>
                    ) : (
                        <span className="block max-w-48 truncate">{id}</span>
                    )}
                </CopyToClipboardInline>
            </LabeledChipValue>
        </LemonTag>
    )
}
