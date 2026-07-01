import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { propertyAccessControlsCreate } from 'products/access_control/frontend/generated/api'
import { AccessLevelEnumApi } from 'products/access_control/frontend/generated/api.schemas'

import { AccessScope, accessDetailLogic } from './accessDetailLogic'
import type { addPropertyRestrictionModalLogicType } from './addPropertyRestrictionModalLogicType'

export interface PropertyOption {
    id: string
    name: string
}

export interface AddPropertyRestrictionModalLogicProps {
    projectId: string
    scopeType: AccessScope
    subjectId: string
}

export const addPropertyRestrictionModalLogic = kea<addPropertyRestrictionModalLogicType>([
    path((key) => ['scenes', 'access_control', 'addPropertyRestrictionModalLogic', key]),
    props({} as AddPropertyRestrictionModalLogicProps),
    key((props) => `${props.projectId}:${props.scopeType}:${props.subjectId}`),

    connect((props: AddPropertyRestrictionModalLogicProps) => ({
        actions: [accessDetailLogic(props), ['loadProperties']],
    })),

    actions({
        openModal: true,
        closeModal: true,
        setPropertyType: (propertyType: 'person' | 'event') => ({ propertyType }),
        setSearch: (search: string) => ({ search }),
        setPropertyId: (propertyId: string | null) => ({ propertyId }),
        setLevel: (level: AccessLevelEnumApi) => ({ level }),
        submitRule: true,
    }),

    reducers({
        isOpen: [false, { openModal: () => true, closeModal: () => false }],
        propertyType: [
            'person' as 'person' | 'event',
            { setPropertyType: (_, { propertyType }) => propertyType, closeModal: () => 'person' },
        ],
        search: ['', { setSearch: (_, { search }) => search, setPropertyType: () => '', closeModal: () => '' }],
        propertyId: [
            null as string | null,
            { setPropertyId: (_, { propertyId }) => propertyId, setPropertyType: () => null, closeModal: () => null },
        ],
        level: [
            AccessLevelEnumApi.Read as AccessLevelEnumApi,
            { setLevel: (_, { level }) => level, closeModal: () => AccessLevelEnumApi.Read },
        ],
    }),

    loaders(({ props, values }) => ({
        propertyOptions: [
            [] as PropertyOption[],
            {
                loadPropertyOptions: async (_, breakpoint) => {
                    await breakpoint(300)
                    const response = await api.get<{ results: { id: string; name: string }[] }>(
                        `api/projects/${props.projectId}/property_definitions/?type=${values.propertyType}&limit=20&search=${encodeURIComponent(
                            values.search
                        )}`
                    )
                    return response.results.map((item) => ({ id: item.id, name: item.name }))
                },
            },
        ],
    })),

    listeners(({ props, actions, values }) => ({
        openModal: () => actions.loadPropertyOptions(null),
        setPropertyType: () => actions.loadPropertyOptions(null),
        setSearch: () => actions.loadPropertyOptions(null),
        submitRule: async () => {
            if (!values.propertyId) {
                return
            }
            try {
                await propertyAccessControlsCreate(props.projectId, {
                    property_definition_id: values.propertyId,
                    access_level: values.level,
                    ...(props.scopeType === 'role'
                        ? { role: props.subjectId }
                        : { organization_member: props.subjectId }),
                })
                lemonToast.success('Property restriction added')
                actions.loadProperties()
                actions.closeModal()
            } catch (e) {
                const error = (e as Record<string, any>).detail || 'Failed to add property restriction'
                lemonToast.error(error)
            }
        },
    })),
])
