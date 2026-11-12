import { useActions, useValues } from 'kea'
import { useId, useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'

import { AccountViewTileHeaderActions } from '../../scenes/CustomerAnalyticsAccountScene/AccountViewTileHeaderActions'
import { DOT_MATRIX_WEEK_OPTIONS, type DotMatrixWeeks } from '../ProductActivity/dotMatrixTileConfig'
import type { accountDotMatrixTileLogic } from './accountDotMatrixTileLogic'
import { DotMatrixSourcePicker } from './DotMatrixSourcePicker'

export function DotMatrixTileSettings({ logic }: { logic: ReturnType<typeof accountDotMatrixTileLogic> }): JSX.Element {
    const id = useId()
    const [open, setOpen] = useState(false)
    const { config, sourceKind, queryEditorOpen } = useValues(logic)
    const { chooseSource, setMode, setWeeks, editQuery } = useActions(logic)
    return (
        <AccountViewTileHeaderActions>
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
                    size="xsmall"
                    type="tertiary"
                    icon={<IconGear />}
                    onClick={() => setOpen(!open)}
                    aria-expanded={open}
                    aria-label="Options"
                    tooltip="Options"
                    data-attr="account-dot-matrix-settings"
                />
            </Popover>
        </AccountViewTileHeaderActions>
    )
}
