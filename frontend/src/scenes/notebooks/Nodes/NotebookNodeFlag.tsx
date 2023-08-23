import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { BindLogic, useActions, useValues } from 'kea'
import { FeatureFlagLogicProps, featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { IconFlag, IconRecording } from 'lib/lemon-ui/icons'
import clsx from 'clsx'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookNodeViewProps } from '../Notebook/utils'
import { buildPlaylistContent } from './NotebookNodePlaylist'
import { buildCodeExampleContent } from './NotebookNodeFlagCodeExample'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'

const Component = (props: NotebookNodeViewProps<NotebookNodeFlagAttributes>): JSX.Element => {
    const { id } = props.node.attrs
    const { featureFlag, featureFlagLoading, recordingFilterForFlag } = useValues(featureFlagLogic({ id }))
    const { expanded } = useValues(notebookNodeLogic)
    const { insertAfter } = useActions(notebookNodeLogic)

    return (
        <div>
            <BindLogic logic={featureFlagLogic} props={{ id }}>
                <div className="flex items-center gap-2 p-4">
                    <IconFlag className="text-lg" />
                    {featureFlagLoading ? (
                        <LemonSkeleton className="h-6 flex-1" />
                    ) : (
                        <>
                            <span className="flex-1 font-semibold truncate">{featureFlag.key}</span>
                            <span
                                className={clsx(
                                    'text-white rounded px-1',
                                    featureFlag.active ? 'bg-success' : 'bg-muted-alt'
                                )}
                            >
                                {featureFlag.active ? 'Enabled' : 'Disabled'}
                            </span>
                        </>
                    )}
                </div>

                {expanded ? (
                    <>
                        <LemonDivider className="my-0" />
                        <div className="p-2">
                            <FeatureFlagReleaseConditions readOnly />
                        </div>
                        <LemonDivider className="my-0" />
                        <div className="p-2 mr-1 flex justify-end gap-2">
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconFlag />}
                                onClick={() => {
                                    insertAfter(buildCodeExampleContent(id))
                                }}
                            >
                                Show implementation
                            </LemonButton>
                            <LemonButton
                                onClick={() => {
                                    insertAfter(buildPlaylistContent(recordingFilterForFlag))
                                }}
                                type="secondary"
                                size="small"
                                icon={<IconRecording />}
                            >
                                View Replays
                            </LemonButton>
                        </div>
                    </>
                ) : null}
            </BindLogic>
        </div>
    )
}

type NotebookNodeFlagAttributes = {
    id: FeatureFlagLogicProps['id']
}

export const NotebookNodeFlag = createPostHogWidgetNode<NotebookNodeFlagAttributes>({
    nodeType: NotebookNodeType.FeatureFlag,
    title: 'Feature Flag',
    Component,
    heightEstimate: '3rem',
    href: (attrs) => urls.featureFlag(attrs.id),
    resizeable: false,
    attributes: {
        id: {},
    },
    pasteOptions: {
        find: urls.featureFlag('') + '(.+)',
        getAttributes: async (match) => {
            return { id: match[1] as FeatureFlagLogicProps['id'] }
        },
    },
})
