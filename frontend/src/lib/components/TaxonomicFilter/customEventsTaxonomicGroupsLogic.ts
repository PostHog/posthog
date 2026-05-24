import { connect, kea, key, path, props, selectors } from 'kea'
import { combineUrl } from 'kea-router'

import { eventTaxonomicGroupProps } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    SimpleOption,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { EventDefinition, EventDefinitionType } from '~/types'

import type { customEventsTaxonomicGroupsLogicType } from './customEventsTaxonomicGroupsLogicType'

export const customEventsTaxonomicGroupsLogic = kea<customEventsTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'customEventsTaxonomicGroupsLogic', key]),

    connect(() => ({
        values: [teamLogic, ['currentTeam'], projectLogic, ['currentProjectId']],
    })),

    selectors({
        customEventsTaxonomicGroups: [
            (s) => [s.currentTeam, s.currentProjectId],
            (currentTeam, projectId): TaxonomicFilterGroup[] => {
                const teamId = currentTeam?.id
                return [
                    {
                        name: 'Autocapture events',
                        searchPlaceholder: 'autocapture events',
                        type: TaxonomicFilterGroupType.AutocaptureEvents,
                        endpoint: `api/environments/${teamId}/events/values/?key=$el_text&event_name=$autocapture`,
                        searchAlias: 'value',
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => `Autocapture event`,
                        minSearchQueryLength: 3,
                        searchDescription: 'element text seen on autocapture events',
                    },
                    {
                        name: 'Custom Events',
                        searchPlaceholder: 'custom events',
                        type: TaxonomicFilterGroupType.CustomEvents,
                        endpoint: combineUrl(`api/projects/${projectId}/event_definitions`, {
                            event_type: EventDefinitionType.EventCustom,
                            exclude_hidden: true,
                        }).url,
                        getName: (eventDefinition: EventDefinition) => eventDefinition.name,
                        getValue: (eventDefinition: EventDefinition) => eventDefinition.name,
                        ...eventTaxonomicGroupProps,
                    },
                ]
            },
        ],
    }),
])
