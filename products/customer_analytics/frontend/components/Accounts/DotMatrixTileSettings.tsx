import { useActions, useValues } from 'kea'
import { useId, useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'

import { DOT_MATRIX_WEEK_OPTIONS, type DotMatrixWeeks } from '../ProductActivity/dotMatrixTileConfig'
import type { accountDotMatrixTileLogic } from './accountDotMatrixTileLogic'
import { DotMatrixSourcePicker } from './DotMatrixSourcePicker'

export function DotMatrixTileSettings({ logic }: { logic: ReturnType<typeof accountDotMatrixTileLogic> }): JSX.Element {
    const id = useId()
    const [open, setOpen] = useState(false)
    const { config, sourceKind, queryEditorOpen } = useValues(logic)
    const { chooseSource, setMode, setWeeks, editQuery } = useActions(logic)
    return (
        <div className="flex flex-wrap items-center justify-end gap-2">
            {sourceKind === 'hogql' && !queryEditorOpen && (
                <LemonButton size="small" onClick={editQuery}>
                    Edit query
                </LemonButton>
            )}
            <Popover
                visible={open}
                onClickOutside={() => setOpen(false)}
                overlay={
                    <div className="flex flex-col gap-3 p-3 w-64">
                        <DotMatrixSourcePicker
                            id={`${id}-source`}
                            value={sourceKind}
                            onChange={(kind) => {
                                chooseSource(kind)
                                setOpen(false)
                            }}
                        />
                        {sourceKind !== 'product_usage' && (
                            <>
                                <LemonLabel htmlFor={`${id}-mode`}>Display</LemonLabel>
                                <LemonSelect<'dots' | 'count'>
                                    id={`${id}-mode`}
                                    value={config.mode}
                                    onChange={setMode}
                                    options={[
                                        { value: 'dots', label: 'Dots' },
                                        { value: 'count', label: 'Count' },
                                    ]}
                                    fullWidth
                                    aria-label="Dot matrix display"
                                    data-attr="account-dot-matrix-mode"
                                />
                            </>
                        )}
                        <LemonLabel htmlFor={`${id}-weeks`}>Weeks</LemonLabel>
                        <LemonSelect<DotMatrixWeeks>
                            id={`${id}-weeks`}
                            value={config.weeks}
                            onChange={setWeeks}
                            options={DOT_MATRIX_WEEK_OPTIONS.map((weeks) => ({
                                value: weeks,
                                label: `${weeks} weeks`,
                            }))}
                            fullWidth
                            aria-label="Dot matrix weeks"
                            data-attr="account-dot-matrix-weeks"
                        />
                    </div>
                }
            >
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconGear />}
                    onClick={() => setOpen(!open)}
                    aria-expanded={open}
                    data-attr="account-dot-matrix-settings"
                >
                    Settings
                </LemonButton>
            </Popover>
        </div>
    )
}
