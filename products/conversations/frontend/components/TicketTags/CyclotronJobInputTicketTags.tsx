import { useValues } from 'kea'

import { LemonInputSelect } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'

import { tagsModel } from '~/models/tagsModel'

export default function CyclotronJobInputTicketTags({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const { tags: tagsAvailable, tagsLoading } = useValues(tagsModel)

    // Render an always-editable multi-select rather than ObjectTags' click-to-edit toggle.
    // ObjectTags collapses back to display mode on blur, which unmounts the input mid-click —
    // inside the ReactFlow node panel that makes removing/adding a tag impossible (the click
    // lands on nothing and ReactFlow treats it as a pane click, deselecting the step).
    return (
        <LemonInputSelect
            mode="multiple"
            allowCustomValues
            value={value ?? []}
            options={tagsAvailable?.map((t) => ({ key: t, label: t }))}
            onChange={onChange}
            loading={tagsLoading}
            placeholder='try "official"'
            data-attr="ticket-tags-input"
        />
    )
}
