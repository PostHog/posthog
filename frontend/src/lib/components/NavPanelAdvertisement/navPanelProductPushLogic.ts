import { afterMount, connect, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'

import { preflightLogic } from 'lib/logic/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import * as api from 'products/growth/frontend/generated/api'
import type { ProductPushCampaignApi } from 'products/growth/frontend/generated/api.schemas'

import type { navPanelProductPushLogicType } from './navPanelProductPushLogicType'

export const navPanelProductPushLogic = kea<navPanelProductPushLogicType>([
    path(['lib', 'components', 'NavPanelAdvertisement', 'navPanelProductPushLogic']),
    connect(() => ({
        values: [
            organizationLogic,
            ['currentOrganization'],
            preflightLogic,
            ['isCloudOrDev'],
            teamLogic,
            ['currentTeamId'],
        ],
    })),
    loaders(({ values }) => ({
        activeCampaign: [
            null as ProductPushCampaignApi | null,
            {
                loadActiveCampaign: async (): Promise<ProductPushCampaignApi | null> => {
                    if (!values.isCloudOrDev || !values.currentOrganization) {
                        return null
                    }

                    try {
                        // team_id lets the backend hide the campaign in projects that already
                        // use the product. 204 (nothing to show) resolves to undefined.
                        return (
                            (await api.productPushCampaignActiveRetrieve(
                                values.currentOrganization.id,
                                values.currentTeamId ? { team_id: values.currentTeamId } : undefined
                            )) ?? null
                        )
                    } catch {
                        // The promo card is best-effort — never surface an error toast for it
                        return null
                    }
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        // The afterMount load may race preflight: its loader gate returns null until
        // preflight resolves, so retry once cloud-ness is actually known.
        [preflightLogic.actionTypes.loadPreflightSuccess]: () => {
            if (values.activeCampaign === null && !values.activeCampaignLoading) {
                actions.loadActiveCampaign()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadActiveCampaign()
    }),
])
