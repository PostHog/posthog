import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInputSelect, type LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

import { CanvasOptionLabel } from './CanvasOptionLabel'
import { canvasPickerLogic } from './canvasPickerLogic'

export type CanvasPickerSelectProps = {
    /** Isolates picker state per mount (modal vs. each tile). */
    pickerKey: string
    value: string | null
    onChange: (canvasId: string | null) => void
    disabled?: boolean
    size?: 'small' | 'medium'
    fullWidth?: boolean
    dataAttr?: string
}

export function CanvasPickerSelect({
    pickerKey,
    value,
    onChange,
    disabled,
    size = 'small',
    fullWidth = false,
    dataAttr,
}: CanvasPickerSelectProps): JSX.Element {
    const logic = canvasPickerLogic({ pickerKey })
    const { canvasOptions, canvasOptionsLoading, canvasOptionsFailed, selectedCanvas, search } = useValues(logic)
    const { ensureOptionsLoaded, retryLoadOptions, setSearch, ensureSelectedLoaded } = useActions(logic)

    // Resolve the selected label even when it falls outside the loaded/searched page.
    useEffect(() => {
        if (value) {
            ensureSelectedLoaded(value)
        }
    }, [value, ensureSelectedLoaded])

    const options = useMemo((): LemonInputSelectOption[] => {
        const byId = new Map<string, CanvasApi>()
        if (selectedCanvas) {
            byId.set(selectedCanvas.id, selectedCanvas)
        }
        for (const canvas of canvasOptions) {
            byId.set(canvas.id, canvas)
        }
        return Array.from(byId.values(), (canvas) => ({
            key: canvas.id,
            label: canvas.name,
            labelComponent: <CanvasOptionLabel canvas={canvas} />,
        }))
    }, [canvasOptions, selectedCanvas])

    return (
        <LemonInputSelect
            mode="single"
            size={size}
            fullWidth={fullWidth}
            placeholder="Select a canvas"
            loading={canvasOptionsLoading}
            disabled={disabled}
            disableFiltering
            value={value ? [value] : []}
            options={options}
            emptyStateComponent={
                canvasOptionsFailed ? (
                    <div className="flex items-center justify-between gap-2 p-1">
                        <span className="text-danger">Couldn't load canvases.</span>
                        <LemonButton size="xsmall" type="secondary" onClick={() => retryLoadOptions()}>
                            Try again
                        </LemonButton>
                    </div>
                ) : (
                    <p className="text-secondary italic p-1">
                        {search ? `No canvases matching "${search}"` : 'No canvases yet'}
                    </p>
                )
            }
            onFocus={() => ensureOptionsLoaded()}
            onInputChange={(text) => setSearch(text)}
            onChange={(values) => onChange(values.length > 0 ? values[0] : null)}
            data-attr={dataAttr}
        />
    )
}
