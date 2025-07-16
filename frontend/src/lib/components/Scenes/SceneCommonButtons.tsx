import { IconCopy, IconShare, IconStar, IconStarFilled } from '@posthog/icons'
import { useActions } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconComment } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import posthog from 'posthog-js'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

type SceneCommonButtonsButtonProps = {
    onClick?: () => void
    active?: boolean
}

type SceneCommonButtonsProps = {
    duplicate?: SceneCommonButtonsButtonProps
    favorite?: SceneCommonButtonsButtonProps
    comment?: boolean
    share?: SceneCommonButtonsButtonProps
}

export function SceneCommonButtons({ duplicate, favorite, comment, share }: SceneCommonButtonsProps): JSX.Element {
    const hasDiscussions = useFeatureFlag('DISCUSSIONS')
    const { openSidePanel } = useActions(sidePanelLogic)

    return (
        <div className="grid grid-cols-2 gap-1">
            {favorite && (
                <ButtonPrimitive
                    onClick={favorite.onClick}
                    tooltip={favorite.active ? 'Remove from favorites' : 'Add to favorites'}
                    active={favorite.active}
                    fullWidth
                    className="justify-center"
                    menuItem
                >
                    {favorite.active ? <IconStarFilled className="text-warning" /> : <IconStar />}
                </ButtonPrimitive>
            )}

            {comment && (
                <ButtonPrimitive
                    onClick={() => {
                        if (!hasDiscussions) {
                            posthog.updateEarlyAccessFeatureEnrollment('discussions', true)
                        }
                        openSidePanel(SidePanelTab.Discussion)
                    }}
                    tooltip="Comment"
                    fullWidth
                    className="justify-center"
                    menuItem
                >
                    <IconComment />
                </ButtonPrimitive>
            )}

            {share && (
                <ButtonPrimitive onClick={share.onClick} tooltip="Share" fullWidth className="justify-center" menuItem>
                    <IconShare />
                </ButtonPrimitive>
            )}

            {duplicate && (
                <ButtonPrimitive
                    onClick={duplicate.onClick}
                    tooltip="Duplicate"
                    fullWidth
                    className="justify-center"
                    menuItem
                >
                    <IconCopy />
                </ButtonPrimitive>
            )}
        </div>
    )
}
