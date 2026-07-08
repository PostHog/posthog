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
    /** The billing feature required to use notifications. Defaults to AUDIT_LOGS; null renders ungated. */
    requiredFeature?: AvailableFeature | null
    /** Where the back arrow on a notification's configuration page should return to */
    returnTo?: string
    /**
     * Hog function type of the sub-template. Internal-event triggers (activity log,
     * feature flag changes) are internal destinations; real captured events (e.g.
     * $mcp_* triggers) are plain destinations. Must match the sub-template's `type`.
     */
    type?: 'destination' | 'internal_destination'
}

export function NotificationsPane({
    subTemplateId,
    description,
    dialogTitle,
    requiredFeature = AvailableFeature.AUDIT_LOGS,
    returnTo,
    type = 'internal_destination',
}: NotificationsPaneProps): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const hogFunctionFilterList = [getFiltersFromSubTemplateId(subTemplateId)].filter(
        (f): f is CyclotronJobFiltersType => !!f
    )

    const listLogicProps = { forceFilterGroups: hogFunctionFilterList, type }
    const { loadHogFunctions } = useActions(hogFunctionsListLogic(listLogicProps))
    const onCreated = (): void => {
        loadHogFunctions()
    }

    const logicProps = { subTemplateId, onCreated }
    const { openDialog } = useActions(newNotificationDialogLogic(logicProps))

    const pane = (
        <div>
            <p>{description}</p>
            <HogFunctionList
                forceFilterGroups={hogFunctionFilterList}
                type={type}
                returnTo={returnTo}
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
    )

    return requiredFeature === null ? pane : <PayGateMini feature={requiredFeature}>{pane}</PayGateMini>
}
