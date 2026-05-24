import { connect, kea, key, path, props, selectors } from 'kea'

import {
    SimpleOption,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { teamLogic } from 'scenes/teamLogic'

import type { shortcutValueTaxonomicGroupsLogicType } from './shortcutValueTaxonomicGroupsLogicType'

export const shortcutValueTaxonomicGroupsLogic = kea<shortcutValueTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'shortcutValueTaxonomicGroupsLogic', key]),

    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),

    selectors({
        shortcutValueTaxonomicGroups: [
            (s) => [s.currentTeam],
            (currentTeam): TaxonomicFilterGroup[] => {
                const teamId = currentTeam?.id
                return [
                    // PageviewUrls returns a URL string value, used in paths and property filters.
                    // PageviewEvents creates a $pageview event with $current_url property filter,
                    // used in trends and funnels series pickers.
                    {
                        name: 'Pageview URLs',
                        searchPlaceholder: 'pageview URLs',
                        type: TaxonomicFilterGroupType.PageviewUrls,
                        endpoint: `api/environments/${teamId}/events/values/?key=$current_url&event_name=$pageview`,
                        searchAlias: 'value',
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => `Pageview URL`,
                        minSearchQueryLength: 3,
                        searchDescription: 'URLs seen on pageview events',
                    },
                    {
                        name: 'Pageview events',
                        searchPlaceholder: 'pageview events',
                        type: TaxonomicFilterGroupType.PageviewEvents,
                        endpoint: `api/environments/${teamId}/events/values/?key=$current_url&event_name=$pageview`,
                        searchAlias: 'value',
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => `Pageview event`,
                        minSearchQueryLength: 3,
                        searchDescription: 'pageview events filtered by URL',
                    },
                    // Screens returns a screen name value, used in paths and property filters.
                    // ScreenEvents creates a $screen event with $screen_name property filter,
                    // used in trends and funnels series pickers.
                    {
                        name: 'Screens',
                        searchPlaceholder: 'screens',
                        type: TaxonomicFilterGroupType.Screens,
                        endpoint: `api/environments/${teamId}/events/values/?key=$screen_name&event_name=$screen`,
                        searchAlias: 'value',
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => `Screen`,
                        minSearchQueryLength: 3,
                        searchDescription: 'screen names seen on screen events',
                    },
                    {
                        name: 'Screen events',
                        searchPlaceholder: 'screen events',
                        type: TaxonomicFilterGroupType.ScreenEvents,
                        endpoint: `api/environments/${teamId}/events/values/?key=$screen_name&event_name=$screen`,
                        searchAlias: 'value',
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => `Screen event`,
                        minSearchQueryLength: 3,
                        searchDescription: 'screen events filtered by screen name',
                    },
                    {
                        name: 'Email addresses',
                        searchPlaceholder: 'email addresses',
                        type: TaxonomicFilterGroupType.EmailAddresses,
                        endpoint: `api/environments/${teamId}/persons/values/?key=email`,
                        searchAlias: 'value',
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => `Email address`,
                        minSearchQueryLength: 5,
                        searchDescription: 'email addresses seen in person properties',
                    },
                ]
            },
        ],
    }),
])
