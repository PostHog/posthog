import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import { AvailableFeature, CyclotronJobFiltersType, HogFunctionSubTemplateIdType } from '~/types'

import { HogFunctionList } from './HogFunctionsList'
import { hogFunctionsListLogic } from './hogFunctionsListLogic'
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

    const hogFunctionFilterList = [getFiltersFromSubTemplateId(subTemplateId)].filter(
        (f): f is CyclotronJobFiltersType => !!f
    )

    const listLogicProps = { forceFilterGroups: hogFunctionFilterList, type: 'internal_destination' as const }
    const { loadHogFunctions } = useActions(hogFunctionsListLogic(listLogicProps))
    const onCreated = (): void => {
        loadHogFunctions()
    }

    const logicProps = { subTemplateId, onCreated }
    const { openDialog } = useActions(newNotificationDialogLogic(logicProps))

    return (
        <PayGateMini feature={requiredFeature}>
            <div>
                <p>{description}</p>
                <HogFunctionList
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
                <NewNotificationDialog subTemplateId={subTemplateId} onCreated={onCreated} title={dialogTitle} />
            </div>
        </PayGateMini>
    )
}
