import { connect, events, kea, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl } from 'kea-router'
import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { teamLogic } from 'scenes/teamLogic'

import { PersonProperty } from '~/types'

import type { personPropertiesModelType } from './personPropertiesModelType'
import { PersonPropertiesModelProps } from './types'

export const personPropertiesModel = kea<personPropertiesModelType>([
    props({} as PersonPropertiesModelProps),
    path(['models', 'personPropertiesModel']),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    loaders(({ values }) => ({
        personProperties: [
            [] as PersonProperty[],
            {
                loadPersonProperties: async () => {
                    const url = combineUrl(`api/projects/${values.currentTeamId}/property_definitions`, {
                        type: 'person',
                        properties: values.propertyAllowList?.[TaxonomicFilterGroupType.PersonProperties]
                            ? values.propertyAllowList[TaxonomicFilterGroupType.PersonProperties].join(',')
                            : undefined,
                    }).url
                    return (await api.get(url)).results
                },
            },
        ],
        linkedViewPersonProperties: [
            [] as PersonProperty[],
            {
                loadLinkedViewPersonProperties: async () => {
                    return []
                },
            },
        ],
    })),
    selectors({
        combinedPersonProperties: [
            (s) => [s.personProperties, s.linkedViewPersonProperties],
            (personProperties, linkedViewPersonProperties) => {
                return [...personProperties, ...linkedViewPersonProperties]
            },
        ],
        propertyAllowList: [
            () => [(_, props) => props.propertyAllowList],
            (propertyAllowList) => propertyAllowList as PersonPropertiesModelProps['propertyAllowList'],
        ],
    }),
    events(({ actions }) => ({
        afterMount: actions.loadPersonProperties,
    })),
])
