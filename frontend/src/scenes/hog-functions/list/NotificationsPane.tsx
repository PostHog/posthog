import { useActions } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import { AvailableFeature, CyclotronJobFiltersType, HogFunctionSubTemplateIdType } from '~/types'

import { HogFunctionList } from './HogFunctionsList'
import { getFiltersFromSubTemplateId } from './LinkedHogFunctions'
import { NewNotificationDialog } from './NewNotificationDialog'
import { newNotificationDialogLogic } from './newNotificationDialogLogic'

export interface NotificationsPaneProps {
    /** The sub-template ID that defines the filters, names, and message templates */
    subTemplateId: HogFunctionSubTemplateIdType
    /** Description shown above the notification list */
    description: string
    /** Title for the new notification dialog */
    dialogTitle?: string
    /** The billing feature required to use notifications. Defaults to AUDIT_LOGS. */
    requiredFeature?: AvailableFeature
}

export function NotificationsPane({
    subTemplateId,
    description,
    dialogTitle,
    requiredFeature = AvailableFeature.AUDIT_LOGS,
}: NotificationsPaneProps): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })
    // Increment to force HogFunctionList to reload after creating a notification
    const [listKey, setListKey] = useState(0)

    const logicProps = { subTemplateId, onCreated: () => setListKey((k) => k + 1) }
    const { openDialog } = useActions(newNotificationDialogLogic(logicProps))

    const hogFunctionFilterList = [getFiltersFromSubTemplateId(subTemplateId)].filter(
        (f): f is CyclotronJobFiltersType => !!f
    )

    return (
        <PayGateMini feature={requiredFeature}>
            <div>
                <p>{description}</p>
                <HogFunctionList
                    key={listKey}
                    forceFilterGroups={hogFunctionFilterList}
                    type="internal_destination"
                    extraControls={
                        <LemonButton
                            type="primary"
                            size="small"
                            disabledReason={restrictedReason ?? undefined}
                            onClick={openDialog}
                        >
                            New notification
                        </LemonButton>
                    }
                />
                <NewNotificationDialog
                    subTemplateId={subTemplateId}
                    onCreated={() => setListKey((k) => k + 1)}
                    title={dialogTitle}
                />
            </div>
        </PayGateMini>
    )
}
