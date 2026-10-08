import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonInputSelect, type LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { fullName } from 'lib/utils/strings'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

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

function CanvasOptionLabel({ canvas }: { canvas: CanvasApi }): JSX.Element {
    const creator = canvas.created_by
    const creatorName = creator ? fullName(creator) || creator.email : null
    return (
        <span className="flex w-full items-center justify-between gap-2">
            <span className="min-w-0 flex-1 truncate">{canvas.name}</span>
            {creator ? (
                <span className="inline-flex shrink-0 items-center gap-1 text-xs text-muted">
                    <ProfilePicture
                        user={{ first_name: creator.first_name, last_name: creator.last_name, email: creator.email }}
                        size="sm"
                    />
                    <span className="max-w-32 truncate">{creatorName}</span>
                </span>
            ) : null}
        </span>
    )
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
    const { canvasOptions, canvasOptionsLoading, selectedCanvas, search } = useValues(logic)
    const { ensureOptionsLoaded, setSearch, ensureSelectedLoaded } = useActions(logic)

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
                <p className="text-secondary italic p-1">
                    {search ? `No canvases matching "${search}"` : 'No canvases yet'}
                </p>
            }
            onFocus={() => ensureOptionsLoaded()}
            onInputChange={(text) => setSearch(text)}
            onChange={(values) => onChange(values.length > 0 ? values[0] : null)}
            data-attr={dataAttr}
        />
    )
}
