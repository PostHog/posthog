import { kea } from 'kea'
import { Framework, PlatformType } from 'scenes/onboarding/types'
import { onboardingLogicType } from 'types/scenes/onboarding/onboardingLogicType'
import { API, MOBILE } from 'scenes/onboarding/constants'

export const onboardingLogic = kea<onboardingLogicType<PlatformType, Framework>>({
    actions: {
        onSubmit: ({ type, framework }: { type?: PlatformType; framework?: Framework }) => ({ type, framework }),
        reverse: true,
        onApiContinue: true,
        onCustomContinue: true,

        setIndex: (index: number) => ({ index }),
        setPath: (path: number[]) => ({ path }),
        setPlatformType: (type: PlatformType) => ({ type }),
        setFramework: (framework: Framework) => ({ framework: framework as Framework }),
    },

    reducers: {
        index: [
            0,
            {
                setIndex: (_, { index }) => index,
            },
        ],
        platformType: [null as null | PlatformType, { setPlatformType: (_, { type }) => type }],
        framework: [null as null | Framework, { setFramework: (_, { framework }) => framework as Framework }],
        path: [[] as number[], { setPath: (_, { path }) => path }],
    },

    listeners: ({ actions, values }) => ({
        onSubmit({ framework, type }) {
            const { index, path } = values

            actions.setPath([...path, index])

            if (index === 0 && type) {
                actions.setPlatformType(type)
                if (type === MOBILE) {
                    actions.setIndex(index + 2)
                    return
                }
            } else if (index === 1) {
                actions.setIndex(4)
                return
            } else if (index === 2 && framework) {
                actions.setFramework(framework as Framework)
            }
            actions.setIndex((index + 1) % 5)
        },

        reverse() {
            const copyPath = [...values.path]
            const prev = copyPath.pop()
            if (typeof prev !== 'undefined') {
                actions.setIndex(prev)
            }
            actions.setPath(copyPath)
        },

        onApiContinue() {
            const { index } = values
            actions.setPath([...values.path, index])
            actions.setFramework(API)
            actions.setIndex(index + 1)
        },

        onCustomContinue() {
            actions.setPath([...values.path, values.index])
            actions.setIndex(2)
        },
    }),
})
