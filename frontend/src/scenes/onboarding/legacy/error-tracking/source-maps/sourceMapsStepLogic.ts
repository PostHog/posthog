import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { ErrorTrackingSymbolSet } from 'lib/components/Errors/types'

import type { sourceMapsStepLogicType } from './sourceMapsStepLogicType'

export type SourceMapOption = 'cli' | 'no-minification' | 'public-source-maps' | string

export const sourceMapsStepLogic = kea<sourceMapsStepLogicType>([
    path(['scenes', 'onboarding', 'error-tracking', 'source-maps', 'sourceMapsStepLogic']),

    actions({
        loadLastSymbolSet: true,
        setSelectedOption: (option: SourceMapOption | null) => ({ option }),
        setInstructionsModalOpen: (open: boolean) => ({ open }),
    }),

    reducers({
        selectedOption: [
            null as SourceMapOption | null,
            {
                setSelectedOption: (_, { option }) => option,
            },
        ],
        instructionsModalOpen: [
            false,
            {
                setInstructionsModalOpen: (_, { open }) => open,
            },
        ],
    }),

    loaders({
        lastSymbolSet: [
            null as ErrorTrackingSymbolSet | null,
            {
                loadLastSymbolSet: async () => {
                    const res = await api.errorTracking.symbolSets.list({
                        status: 'valid',
                        offset: 0,
                        limit: 1,
                    })
                    return res.results?.[0] ?? null
                },
            },
        ],
    }),

    selectors({
        hasSourceMap: [
            (s) => [s.lastSymbolSet],
            (lastSymbolSet: ErrorTrackingSymbolSet | null): boolean => {
                return lastSymbolSet !== null
            },
        ],
        shouldShowContinue: [
            (s) => [s.hasSourceMap, s.selectedOption],
            (hasSourceMap: boolean, selectedOption: SourceMapOption | null): boolean => {
                return hasSourceMap || selectedOption === 'no-minification' || selectedOption === 'public-source-maps'
            },
        ],
        shouldShowSourceMapStatus: [
            (s) => [s.selectedOption],
            (selectedOption: SourceMapOption | null): boolean => {
                return (
                    selectedOption !== null &&
                    selectedOption !== 'no-minification' &&
                    selectedOption !== 'public-source-maps'
                )
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setSelectedOption: () => {
            if (values.shouldShowSourceMapStatus) {
                actions.loadLastSymbolSet()
            }
        },
    })),
])
