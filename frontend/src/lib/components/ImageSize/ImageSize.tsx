import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import type { ImageSizeApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { imageSizeError } from './imageSizeUtils'

export function ImageSize({
    value = {},
    onChange,
    description,
}: {
    value?: ImageSizeApi
    onChange: (value: ImageSizeApi) => void
    description: string
}): JSX.Element {
    const custom = value.width != null || value.height != null
    const error = imageSizeError(value)
    return (
        <LemonCollapse
            panels={[
                {
                    key: 'size',
                    header: `Size: ${custom ? `${value.width ?? 'Auto'} × ${value.height ?? 'Auto'} px` : 'Automatic'}`,
                    content: (
                        <div className="flex flex-col gap-3">
                            <div className="flex flex-wrap gap-3">
                                {(['width', 'height'] as const).map((dimension) => (
                                    <LemonLabel key={dimension} className="flex-1 min-w-32 flex-col items-start gap-1">
                                        <span>{dimension === 'width' ? 'Width' : 'Height'}</span>
                                        <LemonInput
                                            type="number"
                                            value={value[dimension] ?? NaN}
                                            placeholder="Auto"
                                            min={dimension === 'width' ? 320 : 200}
                                            max={dimension === 'width' ? 4000 : 5000}
                                            step={1}
                                            suffix={<span>px</span>}
                                            fullWidth
                                            data-attr={`image-size-${dimension}`}
                                            onChange={(next) =>
                                                onChange({ ...value, [dimension]: Number.isFinite(next) ? next : null })
                                            }
                                        />
                                    </LemonLabel>
                                ))}
                            </div>
                            {error && (
                                <div role="alert" className="text-danger text-sm">
                                    {error}
                                </div>
                            )}
                            <p className="text-secondary text-sm mb-0">{description}</p>
                            {custom && (
                                <LemonButton
                                    size="small"
                                    onClick={() => onChange({ width: null, height: null })}
                                    data-attr="image-size-reset"
                                >
                                    Reset to automatic
                                </LemonButton>
                            )}
                        </div>
                    ),
                },
            ]}
        />
    )
}
