import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import { AvailableFeature, CyclotronJobFiltersType } from '~/types'

import { HogFunctionList } from './HogFunctionsList'
import { hogFunctionsListLogic } from './hogFunctionsListLogic'
import { getFiltersFromSubTemplateId } from './LinkedHogFunctions'
import { NewNotificationDialog } from './NewNotificationDialog'
import { NotificationTriggerOption, newNotificationDialogLogic } from './newNotificationDialogLogic'

export interface NotificationsPaneTrigger extends NotificationTriggerOption {
    /** A listed notification must contain one of these. Defaults to the trigger's filters. */
    listFilterGroups?: CyclotronJobFiltersType[]
}

export interface NotificationsPaneProps {
    triggers: NotificationsPaneTrigger[]
    /** Description shown above the notification list */
    description: string
    /** Title for the new notification dialog */
    dialogTitle?: string
    /** The billing feature required to use notifications. Defaults to AUDIT_LOGS. */
    requiredFeature?: AvailableFeature
    /** Where the back arrow on a notification's configuration page should return to */
    returnTo?: string
    /** Appended to new notifications' names, e.g. the flag key */
    scopeLabel?: string
    emptyText?: string
}

function listFilterGroupsFor(trigger: NotificationsPaneTrigger): CyclotronJobFiltersType[] {
    if (trigger.listFilterGroups) {
        return trigger.listFilterGroups
    }
    const filters = trigger.filters ?? getFiltersFromSubTemplateId(trigger.subTemplateId)
    return filters ? [filters] : []
}

export function NotificationsPane({
    triggers,
    description,
    dialogTitle,
    requiredFeature = AvailableFeature.AUDIT_LOGS,
    returnTo,
    scopeLabel,
    emptyText = 'No notifications set up yet.',
}: NotificationsPaneProps): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const hogFunctionFilterList = triggers.flatMap(listFilterGroupsFor)

    const listLogicProps = { forceFilterGroups: hogFunctionFilterList, type: 'internal_destination' as const }
    const { loadHogFunctions } = useActions(hogFunctionsListLogic(listLogicProps))
    const onCreated = (): void => {
        loadHogFunctions()
    }

    const { openDialog } = useActions(newNotificationDialogLogic({ triggers, onCreated, scopeLabel }))

    return (
        <PayGateMini feature={requiredFeature} featureDetail="hog-function-notifications">
            <div>
                <p>{description}</p>
                <HogFunctionList
                    forceFilterGroups={hogFunctionFilterList}
                    type="internal_destination"
                    returnTo={returnTo}
                    emptyText={emptyText}
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
                    triggers={triggers}
                    onCreated={onCreated}
                    title={dialogTitle}
                    scopeLabel={scopeLabel}
                />
            </div>
        </PayGateMini>
    )
}
