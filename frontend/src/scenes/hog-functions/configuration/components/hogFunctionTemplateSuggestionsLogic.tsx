import { STL as HOG_STL } from '@posthog/hogvm'
import FuseClass from 'fuse.js'
import { actions, kea, key, path, props, reducers, selectors } from 'kea'

import type { hogFunctionTemplateSuggestionsLogicType } from './hogFunctionTemplateSuggestionsLogicType'

export type HogFunctionTemplateOption = {
    key: string
    description: string
    example: string
}

export type HogFunctionTemplateOptionCategory = {
    category: string
    options: HogFunctionTemplateOption[]
}

export type HogFunctionTemplateSuggestionsLogicProps = {
    templating: 'hog' | 'liquid'
}

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<HogFunctionTemplateOption> {}

const HOG_USAGE_EXAMPLES: HogFunctionTemplateOption[] = [
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

const HOG_STL_EXAMPLES: HogFunctionTemplateOption[] = Object.entries(HOG_STL).map(([key, value]) => ({
    key,
    example: value.example,
    description: value.description,
}))

export const hogFunctionTemplateSuggestionsLogic = kea<hogFunctionTemplateSuggestionsLogicType>([
    props({} as HogFunctionTemplateSuggestionsLogicProps),
    key(({ templating }: HogFunctionTemplateSuggestionsLogicProps) => templating),

    path((key) => ['scenes', 'hog-functions', 'configuration', 'hogFunctionTemplateSuggestionsLogic', key]),
    actions({
        setSearch: (search: string) => ({ search }),
    }),
    reducers({
        search: ['' as string, { setSearch: (_, { search }) => search }],
    }),

    selectors({
        allOptions: [
            (_, p) => [p.templating],
            (templating): HogFunctionTemplateOption[] => {
                return templating === 'hog' ? [...HOG_USAGE_EXAMPLES, ...HOG_STL_EXAMPLES] : []
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
            (allOptions, optionsFuse, search) => {
                if (!search) {
                    return allOptions
                }
                return optionsFuse.search(search).map((result) => result.item)
            },
        ],
    }),
])
