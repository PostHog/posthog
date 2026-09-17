import { useValues } from 'kea'

import { SceneTagsCombobox } from 'lib/components/Scenes/SceneTagsCombobox'

import { tagsModel } from '~/models/tagsModel'

type InsightMenuBarTagsProps = {
    onSave: (tags: string[]) => void
    tags?: string[]
    canEdit: boolean
    loading: boolean
}

export function InsightMenuBarTags({ onSave, tags, canEdit, loading }: InsightMenuBarTagsProps): JSX.Element {
    const { tags: tagsAvailable } = useValues(tagsModel)

    return (
        <SceneTagsCombobox
            onSave={onSave}
            tags={tags}
            tagsAvailable={tagsAvailable}
            dataAttrKey="insight"
            canEdit={canEdit}
            loading={loading}
        />
    )
}
