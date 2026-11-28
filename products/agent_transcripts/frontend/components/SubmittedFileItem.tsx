import { IconDocument } from '@posthog/icons'
import { Badge, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

export interface SubmittedFileItemProps {
    fileName: string | null
    submittedAt: string | null
    statusLabel: string
    statusVariant: 'info' | 'success' | 'default'
}

/** The uploaded file and where its review stands. */
export function SubmittedFileItem({
    fileName,
    submittedAt,
    statusLabel,
    statusVariant,
}: SubmittedFileItemProps): JSX.Element {
    return (
        <Item variant="outline" className="w-full max-w-md text-left" data-attr="agent-transcript-submitted-file">
            <ItemMedia variant="icon">
                <IconDocument />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemTitle className="min-w-0 truncate" translate="no">
                    {fileName}
                </ItemTitle>
                <ItemDescription>
                    <span>Uploaded </span>
                    {submittedAt ? <TZLabel time={submittedAt} /> : <span>recently</span>}
                </ItemDescription>
            </ItemContent>
            <ItemActions>
                <Badge variant={statusVariant}>{statusLabel}</Badge>
            </ItemActions>
        </Item>
    )
}
