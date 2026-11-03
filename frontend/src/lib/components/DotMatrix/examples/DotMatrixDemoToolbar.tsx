import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import type { DotMatrixDemoMode } from './dotMatrixDemoLogic'
import { type DotMatrixMockDatasetName } from './dotMatrixMockTypes'

interface DotMatrixDemoToolbarProps {
    datasetName: DotMatrixMockDatasetName
    mode: DotMatrixDemoMode
    colorMode: 'family' | 'product'
    setDatasetName: (dataset: DotMatrixMockDatasetName) => void
    setMode: (mode: DotMatrixDemoMode) => void
    setColorMode: (mode: 'family' | 'product') => void
}

export function DotMatrixDemoToolbar({
    datasetName,
    mode,
    colorMode,
    setDatasetName,
    setMode,
    setColorMode,
}: DotMatrixDemoToolbarProps): JSX.Element {
    const isProducts = datasetName === 'product_activity'
    return (
        <div className="DotMatrixDemo__toolbar">
            <div className="DotMatrixDemo__dataset">
                <LemonSelect
                    value={datasetName}
                    onChange={setDatasetName}
                    options={[
                        { value: 'product_activity', label: 'Product activity' },
                        { value: 'people', label: 'People in one account' },
                        { value: 'ci', label: 'CI health' },
                    ]}
                    size="small"
                    data-attr="dot-matrix-dataset"
                />
                <span className="text-muted text-xs">Mock data</span>
            </div>
            <div className="DotMatrixDemo__controls">
                {isProducts && (
                    <LemonSelect
                        value={colorMode}
                        onChange={setColorMode}
                        options={[
                            { value: 'family', label: 'Color per family' },
                            { value: 'product', label: 'Color per product' },
                        ]}
                        size="small"
                    />
                )}
                <span className="DotMatrixDemo__range">Last 8 weeks</span>
                <LemonSegmentedButton
                    value={mode}
                    onChange={setMode}
                    size="small"
                    options={[
                        { value: 'count', label: 'Count', 'data-attr': 'dot-matrix-count-mode' },
                        {
                            value: 'products',
                            label: isProducts ? 'Products' : 'Dots',
                            'data-attr': 'dot-matrix-dots-mode',
                        },
                        ...(isProducts
                            ? [
                                  { value: 'users' as const, label: 'Users', 'data-attr': 'dot-matrix-users-mode' },
                                  {
                                      value: 'account' as const,
                                      label: 'Account',
                                      'data-attr': 'dot-matrix-account-mode',
                                  },
                              ]
                            : []),
                    ]}
                />
            </div>
        </div>
    )
}
