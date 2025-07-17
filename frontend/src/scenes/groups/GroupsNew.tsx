import { LemonButton } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { groupsNewLogic } from 'scenes/groups/groupsNewLogic'
import { useValues } from 'kea'

interface GroupsNewSceneProps {
    groupTypeIndex?: string
}

export const scene: SceneExport = {
    component: GroupsNew,
    logic: groupsNewLogic,
    paramsToProps: ({ params: { groupTypeIndex } }: { params: GroupsNewSceneProps }) => ({
        groupTypeIndex: parseInt(groupTypeIndex ?? '0'),
    }),
}

export function GroupsNew(): JSX.Element {
    const { logicProps } = useValues(groupsNewLogic)

    return (
        <div className="groups-new">
            <PageHeader
                buttons={
                    <div className="flex items-center gap-2">
                        <LemonButton
                            data-attr="cancel-group"
                            type="secondary"
                            onClick={() => {
                                router.actions.push(urls.groups(logicProps.groupTypeIndex))
                            }}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton type="primary" data-attr="save-group" htmlType="submit" form="group">
                            Save
                        </LemonButton>
                    </div>
                }
            />
        </div>
    )
}
