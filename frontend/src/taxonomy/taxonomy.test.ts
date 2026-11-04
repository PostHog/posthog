import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import type * as hiddenEventsModule from 'lib/components/TaxonomicFilter/utils/hiddenEvents'

import type * as helpersModule from './helpers'
import type * as loaderModule from './loadCoreFilterDefinitions'
import type * as taxonomyModule from './taxonomy'

type Modules = {
    taxonomy: typeof taxonomyModule
    helpers: typeof helpersModule
    hiddenEvents: typeof hiddenEventsModule
    loader: typeof loaderModule
}

describe('core filter definitions', () => {
    it.each<[string, (modules: Modules) => unknown, unknown, unknown]>([
        [
            'an event label',
            ({ helpers }) => helpers.getFilterLabel('$pageview', TaxonomicFilterGroupType.Events),
            '$pageview',
            'Pageview',
        ],
        [
            'a group property definition',
            ({ helpers }) => helpers.getCoreFilterDefinition('$group_key', 'groups_0' as TaxonomicFilterGroupType),
            null,
            expect.objectContaining({ label: 'Group key' }),
        ],
        [
            'the filter type of a property',
            ({ helpers }) => helpers.getFirstFilterTypeFor('$browser'),
            null,
            TaxonomicFilterGroupType.EventProperties,
        ],
        [
            'session duration as a numerical event property',
            ({ taxonomy }) => taxonomy.CORE_FILTER_DEFINITIONS_BY_GROUP.numerical_event_properties.$session_duration,
            undefined,
            expect.objectContaining({ label: 'Session duration' }),
        ],
        [
            'the events hidden from query builders',
            ({ hiddenEvents }) => hiddenEvents.eventsWithMoveNotice(undefined, true),
            [],
            ['$feature_flag_called'],
        ],
        ['the property key list', ({ taxonomy }) => taxonomy.PROPERTY_KEYS.includes('$browser'), false, true],
    ])('reads %s safely before the load and fully after it', async (_name, read, beforeLoad, afterLoad) => {
        // The jest setup fills the shared taxonomy, so read a fresh copy that starts empty, as on a page load.
        await jest.isolateModulesAsync(async () => {
            const modules: Modules = {
                taxonomy: require('./taxonomy'),
                helpers: require('./helpers'),
                hiddenEvents: require('lib/components/TaxonomicFilter/utils/hiddenEvents'),
                loader: require('./loadCoreFilterDefinitions'),
            }

            expect(read(modules)).toEqual(beforeLoad)

            await modules.loader.loadCoreFilterDefinitions()
            expect(read(modules)).toEqual(afterLoad)
        })
    })
})
