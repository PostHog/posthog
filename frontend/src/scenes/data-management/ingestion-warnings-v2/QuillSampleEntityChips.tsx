import { Chip, ChipGroup } from '@posthog/quill'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { IngestionWarningV2Sample } from './ingestionWarningsV2Logic'
import { SampleEntity, sampleEntities } from './sampleEntities'

function EntityChip({ label, value, to }: SampleEntity): JSX.Element {
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
    const entities = sampleEntities(sample)
    if (entities.length === 0) {
        return null
    }
    return (
        <ChipGroup>
            {entities.map((entity) => (
                <EntityChip key={entity.label} {...entity} />
            ))}
        </ChipGroup>
    )
}
