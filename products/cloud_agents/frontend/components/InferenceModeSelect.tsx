import { useValues } from 'kea'

import { LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'

import type { InferenceModeEnumApi } from '../generated/api.schemas'
import { cloudAgentsCatalogLogic } from '../logics/cloudAgentsCatalogLogic'
import { INFERENCE_MODE_DISPLAY } from '../utils/runStatus'

/** A select of who provides and pays for the model. Each option explains itself in one line. */
export function InferenceModeSelect({
    value,
    onChange,
    emptyLabel,
    'data-attr': dataAttr,
}: {
    value: InferenceModeEnumApi | null
    onChange: (mode: InferenceModeEnumApi | null) => void
    emptyLabel?: string
    'data-attr'?: string
}): JSX.Element {
    const { inferenceModes, catalogLoading } = useValues(cloudAgentsCatalogLogic)
    const options: LemonSelectOption<InferenceModeEnumApi | null>[] = [
        ...(emptyLabel ? [{ value: null, label: emptyLabel }] : []),
        ...inferenceModes.map((mode) => ({
            value: mode,
            label: INFERENCE_MODE_DISPLAY[mode]?.label ?? mode,
            labelInMenu: (
                <div className="flex flex-col py-1 whitespace-normal">
                    <span>{INFERENCE_MODE_DISPLAY[mode]?.label ?? mode}</span>
                    <span className="text-secondary text-xs font-normal">
                        {INFERENCE_MODE_DISPLAY[mode]?.description}
                    </span>
                </div>
            ),
        })),
    ]
    return (
        <div className="flex flex-col gap-1">
            <LemonSelect
                fullWidth
                value={value}
                onChange={onChange}
                options={options}
                loading={catalogLoading}
                placeholder="Choose who provides the model"
                data-attr={dataAttr}
            />
            {value && INFERENCE_MODE_DISPLAY[value] && (
                <p className="text-secondary text-xs m-0">{INFERENCE_MODE_DISPLAY[value].description}</p>
            )}
        </div>
    )
}
