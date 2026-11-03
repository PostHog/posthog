import { actions, kea, key, path, props, reducers, selectors, type LogicWrapper, type MakeLogicType } from 'kea'

import { getDotMatrixDemoDisplay, type DotMatrixDemoDisplay } from './dotMatrixDemoData'
import { getDotMatrixDemoPresentation, type DotMatrixDemoPresentation } from './dotMatrixDemoPresentation'
import { type DotMatrixMockDataset, type DotMatrixMockDatasetName } from './dotMatrixMockTypes'
import { getDotMatrixMockDataset } from './mocks'

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
    dataset: DotMatrixMockDataset
    presentation: DotMatrixDemoPresentation
    display: DotMatrixDemoDisplay
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
    selectors({
        dataset: [(s) => [s.datasetName], (datasetName): DotMatrixMockDataset => getDotMatrixMockDataset(datasetName)],
        presentation: [
            (s) => [s.datasetName, s.selectedSeries],
            (datasetName, selectedSeries): DotMatrixDemoPresentation =>
                getDotMatrixDemoPresentation(datasetName, selectedSeries),
        ],
        display: [
            (s) => [s.dataset, s.datasetName, s.mode, s.selectedSeries, s.colorMode, s.activeAccount],
            (dataset, datasetName, mode, selectedSeries, colorMode, activeAccount): DotMatrixDemoDisplay =>
                getDotMatrixDemoDisplay(dataset, datasetName, mode, selectedSeries, colorMode, activeAccount),
        ],
    }),
])
