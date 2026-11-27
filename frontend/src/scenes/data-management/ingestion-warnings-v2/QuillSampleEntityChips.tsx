import { Chip, ChipGroup } from '@posthog/quill'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { IngestionWarningV2Sample } from './ingestionWarningsV2Logic'

function EntityChip({ label, value, to }: { label: string; value: string | null; to?: string }): JSX.Element | null {
    if (!value) {
        return null
    }
    return (
        <Chip className="max-w-full min-w-0 font-mono">
            <span className="shrink-0 text-muted-foreground">{label}</span>
            {to ? (
                <LinkPrimitive to={to} className="min-w-0 truncate underline-offset-2 hover:underline">
                    {value}
                </LinkPrimitive>
            ) : (
                <CopyToClipboardInline explicitValue={value} description={label} iconSize="xsmall">
                    <span className="min-w-0 truncate">{value}</span>
                </CopyToClipboardInline>
            )}
        </Chip>
    )
}

/** The person, event and group a sample points at, each linked or copyable. */
export function QuillSampleEntityChips({ sample }: { sample: IngestionWarningV2Sample }): JSX.Element | null {
    if (!sample.distinct_id && !sample.person_id && !sample.event_uuid && !sample.group_key) {
        return null
    }
    return (
        <ChipGroup>
            <EntityChip
                label="distinct_id"
                value={sample.distinct_id}
                to={sample.distinct_id ? urls.personByDistinctId(sample.distinct_id) : undefined}
            />
            <EntityChip
                label="person_id"
                value={sample.person_id}
                to={sample.person_id ? urls.personByUUID(sample.person_id) : undefined}
            />
            <EntityChip
                label="event_uuid"
                value={sample.event_uuid}
                to={sample.event_uuid ? urls.event(sample.event_uuid, sample.timestamp) : undefined}
            />
            <EntityChip label="group_key" value={sample.group_key} />
        </ChipGroup>
    )
}
