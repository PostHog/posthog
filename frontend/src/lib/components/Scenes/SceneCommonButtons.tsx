import { IconCopy, IconDashboard, IconNotebook, IconStar, IconStarFilled } from '@posthog/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { SceneNotebookDropdownMenu } from './SceneNotebookDropdownMenu'
import { NotebookNodeType } from '~/types'
import { NodeKind } from '~/queries/schema/schema-general'
import { IconWithCount, IconWithPlus } from 'lib/lemon-ui/icons/icons'

type SceneCommonButtonsButtonProps = {
    onClick?: () => void
    active?: boolean
}

type SceneCommonButtonsProps = {
    dashboard?: SceneCommonButtonsButtonProps
    duplicate?: SceneCommonButtonsButtonProps
    favorite?: SceneCommonButtonsButtonProps
    notebook?: SceneCommonButtonsButtonProps
    shortId?: string
}

export function SceneCommonButtons({
    dashboard,
    duplicate,
    favorite,
    notebook,
    shortId,
}: SceneCommonButtonsProps): JSX.Element {
    return (
        <div className="flex gap-1">
            {duplicate && (
                <ButtonPrimitive onClick={duplicate.onClick} tooltip="Duplicate" iconOnly active={duplicate.active}>
                    <IconCopy />
                </ButtonPrimitive>
            )}

            {favorite && (
                <ButtonPrimitive
                    onClick={favorite.onClick}
                    tooltip={favorite.active ? 'Remove from favorites' : 'Add to favorites'}
                    iconOnly
                    active={favorite.active}
                >
                    {favorite.active ? <IconStarFilled className="text-warning" /> : <IconStar />}
                </ButtonPrimitive>
            )}

            {dashboard && (
                <ButtonPrimitive
                    onClick={dashboard.onClick}
                    tooltip="Add to dashboard"
                    iconOnly
                    active={dashboard.active}
                >
                    <IconWithPlus>
                        <IconDashboard />
                    </IconWithPlus>
                </ButtonPrimitive>
            )}

            {notebook && shortId && (
                <SceneNotebookDropdownMenu
                    buttonProps={(count) => ({
                        iconOnly: true,
                        tooltip: 'Add to notebook',
                        active: notebook.active,
                        children: (
                            <IconWithCount count={count} showZero={false}>
                                <IconWithPlus>
                                    <IconNotebook />
                                </IconWithPlus>
                            </IconWithCount>
                        ),
                    })}
                    notebookSelectButtonProps={{
                        resource: {
                            type: NotebookNodeType.Query,
                            attrs: {
                                query: {
                                    kind: NodeKind.SavedInsightNode,
                                    shortId: shortId,
                                },
                            },
                        },
                    }}
                />
            )}
        </div>
    )
}
