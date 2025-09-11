import FuseClass from 'fuse.js'
import { actions, kea, key, path, props, reducers, selectors } from 'kea'

import { STL as HOG_STL } from '@posthog/hogvm'

import type { cyclotronJobTemplateSuggestionsLogicType } from './cyclotronJobTemplateSuggestionsLogicType'

export type CyclotronJobTemplateOption = {
    key: string
    description: string
    example: string
}

export type CyclotronJobTemplateOptionCategory = {
    category: string
    options: CyclotronJobTemplateOption[]
}

export type CyclotronJobTemplateSuggestionsLogicProps = {
    templating: 'hog' | 'liquid'
}

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<CyclotronJobTemplateOption> {}

const HOG_USAGE_EXAMPLES: CyclotronJobTemplateOption[] = [
    {
        key: 'ternary',
        example: `$1 = true ? 'Yes' : 'No'`,
        description: 'Ternary operation (if this then that else other)',
    },
    {
        key: 'default',
        example: `$1 ?? 'Default value'`,
        description: 'Default value (if this is null or undefined, use this)',
    },
]

const HOG_STL_EXAMPLES: CyclotronJobTemplateOption[] = Object.entries(HOG_STL).map(([key, value]) => ({
    key,
    example: value.example,
    description: value.description,
}))

const LIQUID_USAGE_EXAMPLES: CyclotronJobTemplateOption[] = [
    {
        key: 'property',
        example: `{{ person.properties.email }}`,
        description: 'Access a property of an event or person',
    },
    {
        key: 'if',
        example: `{% if condition %} Yes {% else %} No {% endif %}`,
        description: 'Conditional (if this then that else other)',
    },
    {
        key: 'date',
        example: `{{ person.properties.signed_up_at | date: '%Y-%m-%d' }}`,
        description: 'Format a timestamp',
    },
    {
        key: 'join',
        example: `{{ 'John, Paul, George, Ringo' | split: ', ' | join: ' and ' }}`,
        description: 'Join an array of values into a string',
    },
    {
        key: 'default',
        example: `{{ person.properties.created_at | default: 'Default value' }}`,
        description: 'Default value (if value is null or undefined, use this)',
    },
]

export const cyclotronJobTemplateSuggestionsLogic = kea<cyclotronJobTemplateSuggestionsLogicType>([
    props({} as CyclotronJobTemplateSuggestionsLogicProps),
    key(({ templating }: CyclotronJobTemplateSuggestionsLogicProps) => templating),

    path((key) => ['components', 'cyclotron-jobs', 'cyclotronJobTemplateSuggestionsLogic', key]),
    actions({
        setSearch: (search: string) => ({ search }),
    }),
    reducers({
        search: ['' as string, { setSearch: (_, { search }) => search }],
    }),

    selectors({
        allOptions: [
            (_, p) => [p.templating],
            (templating): CyclotronJobTemplateOption[] => {
                return templating === 'hog' ? [...HOG_USAGE_EXAMPLES, ...HOG_STL_EXAMPLES] : LIQUID_USAGE_EXAMPLES
            },
        ],

        optionsFuse: [
            (s) => [s.allOptions],
            (allOptions): Fuse => {
                return new FuseClass(allOptions, {
                    keys: ['description', 'example'],
                    threshold: 0.3,
                })
            },
        ],

        optionsFiltered: [
            (s) => [s.allOptions, s.optionsFuse, s.search],
            (allOptions, optionsFuse, search): CyclotronJobTemplateOption[] => {
                if (!search) {
                    return allOptions
                }
                return optionsFuse.search(search).map((result) => result.item)
            },
        ],
    }),
])
