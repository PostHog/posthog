import { useValues } from 'kea'

import { SceneTagsCombobox } from 'lib/components/Scenes/SceneTagsCombobox'

import { tagsModel } from '~/models/tagsModel'

type DashboardMenuBarTagsProps = {
    onSave: (tags: string[]) => void
    tags?: string[]
    canEdit: boolean
    loading: boolean
}

export function DashboardMenuBarTags({ onSave, tags, canEdit, loading }: DashboardMenuBarTagsProps): JSX.Element {
    const { tags: tagsAvailable } = useValues(tagsModel)

    return (
        <SceneTagsCombobox
            onSave={onSave}
            tags={tags}
            tagsAvailable={tagsAvailable.filter((tag) => !tags?.includes(tag))}
            dataAttrKey="dashboard"
            canEdit={canEdit}
            loading={loading}
        />
    )
}
