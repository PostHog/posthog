import { IconCheck, IconX } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getApproveDisabledReason, getChangeRequestButtonVisibility } from 'scenes/approvals/changeRequestsLogic'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { ChangeRequestActionsProps, changeRequestDialogHandlers } from './ChangeRequestActions'

const RESOURCE_TYPE = 'change-request'

type ApprovalDetailSceneMenuBarProps = Pick<
    ChangeRequestActionsProps,
    'changeRequest' | 'onApprove' | 'onReject' | 'onCancel'
>

export function ApprovalDetailSceneMenuBar(props: ApprovalDetailSceneMenuBarProps): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    return sceneMenuBarEnabled ? <ApprovalDetailSceneMenuBarInner {...props} /> : null
}

function ApprovalDetailSceneMenuBarInner(props: ApprovalDetailSceneMenuBarProps): JSX.Element {
    const { changeRequest } = props
    const { showApproveButton, showRejectButton, showCancelButton } = getChangeRequestButtonVisibility(changeRequest)
    const approveDisabledReason = getApproveDisabledReason(changeRequest)
    const { handleApprove, handleReject, handleCancel } = changeRequestDialogHandlers(props)

    const actions: SceneAction[] = [
        ...(showApproveButton || approveDisabledReason
            ? ([
                  {
                      group: 'edit',
                      section: 'decision',
                      id: `${RESOURCE_TYPE}-menubar-approve`,
                      label: 'Approve',
                      icon: <IconCheck />,
                      opensFloatingUi: true,
                      disabledReason: showApproveButton ? undefined : (approveDisabledReason ?? undefined),
                      onSelect: handleApprove,
                      pinned: { order: 1, variant: 'primary' },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(showRejectButton
            ? ([
                  {
                      group: 'edit',
                      section: 'decision',
                      id: `${RESOURCE_TYPE}-menubar-reject`,
                      label: 'Reject',
                      icon: <IconX />,
                      opensFloatingUi: true,
                      onSelect: handleReject,
                      pinned: { order: 1, variant: 'secondary' },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(showCancelButton
            ? ([
                  {
                      group: 'edit',
                      section: 'cancel',
                      id: `${RESOURCE_TYPE}-menubar-cancel`,
                      label: 'Cancel request',
                      opensFloatingUi: true,
                      onSelect: handleCancel,
                      pinned: { order: 2, variant: 'secondary' },
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
