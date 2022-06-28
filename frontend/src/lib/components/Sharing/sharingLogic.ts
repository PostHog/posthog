import { afterMount, kea, key, path, props } from 'kea'
import { InsightShortId, SharingConfigurationType } from '~/types'

import api from 'lib/api'
import { loaders } from 'kea-loaders'
import { getInsightId } from 'scenes/insights/utils'

import type { sharingLogicType } from './sharingLogicType'

export interface SharingLogicProps {
    dashboardId?: number
    insightShortId?: InsightShortId
}

const propsToApiParams = async (props: SharingLogicProps): Promise<{ dashboardId?: number; insightId?: number }> => {
    const insightId = props.insightShortId ? await getInsightId(props.insightShortId) : undefined
    return {
        dashboardId: props.dashboardId,
        insightId,
    }
}

export const sharingLogic = kea<sharingLogicType>([
    path(['lib', 'components', 'Sharing', 'sharingLogic']),
    props({} as SharingLogicProps),
    key(({ insightShortId, dashboardId }) => `sharing-${insightShortId || dashboardId}`),

    loaders(({ props }) => ({
        sharingConfiguration: {
            __default: undefined as unknown as SharingConfigurationType,
            loadSharingConfiguration: async () => {
                return await api.sharing.get(await propsToApiParams(props))
            },
            setIsEnabled: async (enabled: boolean) => {
                return await api.sharing.update(await propsToApiParams(props), { enabled })
            },
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSharingConfiguration()
    }),
])
