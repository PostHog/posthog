import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { useValues } from 'kea'
import { FeatureFlagLogicProps, featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { IconFlag, IconRecording } from 'lib/lemon-ui/icons'
import clsx from 'clsx'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookNodeViewProps } from '../Notebook/utils'

const Component = (props: NotebookNodeViewProps<NotebookNodeFlagAttributes>): JSX.Element => {
    const { id } = props.node.attrs
    const logic = featureFlagLogic({ id })
    const { featureFlag, featureFlagLoading } = useValues(logic)
    const { expanded } = useValues(notebookNodeLogic)

    return (
        <div>
            <div className="flex items-center gap-2 p-4">
                <IconFlag className="text-lg" />
                {featureFlagLoading ? (
                    <LemonSkeleton className="h-6 flex-1" />
                ) : (
                    <>
                        <span className="flex-1 font-semibold truncate">{featureFlag.name}</span>
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
                        <p>More info here!</p>
                    </div>
                    <LemonDivider className="my-0" />
                    <div className="p-2 flex justify-end">
                        <LemonButton type="secondary" size="small" icon={<IconRecording />}>
                            View Replays
                        </LemonButton>
                    </div>
                </>
            ) : null}
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
