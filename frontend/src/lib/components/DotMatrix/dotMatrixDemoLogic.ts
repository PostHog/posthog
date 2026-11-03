import { actions, kea, key, path, props, reducers, type LogicWrapper, type MakeLogicType } from 'kea'

import type { DotMatrixMockDatasetName } from './mocks'

export type DotMatrixDemoMode = 'products' | 'count' | 'users' | 'account'
export interface DotMatrixDemoLogicProps {
    instanceId: string
    initialDataset?: DotMatrixMockDatasetName
    initialMode?: DotMatrixDemoMode
    initialSelection?: string[]
    initialColorMode?: 'family' | 'product'
}
export interface dotMatrixDemoLogicValues {
    datasetName: DotMatrixMockDatasetName
    mode: DotMatrixDemoMode
    selectedSeries: string[]
    colorMode: 'family' | 'product'
    activeAccount: string
}
export interface dotMatrixDemoLogicActions {
    openAccount: (activeAccount: string) => { activeAccount: string }
    setDatasetName: (datasetName: DotMatrixMockDatasetName) => { datasetName: DotMatrixMockDatasetName }
    setMode: (mode: DotMatrixDemoMode) => { mode: DotMatrixDemoMode }
    setSelectedSeries: (selectedSeries: string[]) => { selectedSeries: string[] }
    setColorMode: (colorMode: 'family' | 'product') => { colorMode: 'family' | 'product' }
}
export type dotMatrixDemoLogicType = MakeLogicType<
    dotMatrixDemoLogicValues,
    dotMatrixDemoLogicActions,
    DotMatrixDemoLogicProps
>

export const dotMatrixDemoLogic: LogicWrapper<dotMatrixDemoLogicType> = kea<dotMatrixDemoLogicType>([
    props({} as DotMatrixDemoLogicProps),
    key((props) => props.instanceId),
    path((key) => ['lib', 'components', 'DotMatrix', 'dotMatrixDemoLogic', key]),
    actions({
        openAccount: (activeAccount: string) => ({ activeAccount }),
        setDatasetName: (datasetName: DotMatrixMockDatasetName) => ({ datasetName }),
        setMode: (mode: DotMatrixDemoMode) => ({ mode }),
        setSelectedSeries: (selectedSeries: string[]) => ({ selectedSeries }),
        setColorMode: (colorMode: 'family' | 'product') => ({ colorMode }),
    }),
    reducers(({ props }) => ({
        datasetName: [
            props.initialDataset ?? 'product_activity',
            { setDatasetName: (_, { datasetName }) => datasetName },
        ],
        mode: [
            props.initialMode ?? 'products',
            {
                setMode: (_, { mode }) => mode,
                openAccount: () => 'account',
                setDatasetName: (mode) => (mode === 'users' || mode === 'account' ? 'products' : mode),
            },
        ],
        selectedSeries: [
            props.initialSelection ?? [],
            { setSelectedSeries: (_, { selectedSeries }) => selectedSeries, setDatasetName: () => [] },
        ],
        activeAccount: ['acme', { openAccount: (_, { activeAccount }) => activeAccount }],
        colorMode: [props.initialColorMode ?? 'family', { setColorMode: (_, { colorMode }) => colorMode }],
    })),
])
