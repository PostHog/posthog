import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { ImageSizeApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { ImageSize } from './ImageSize'
import { imageSizeError } from './imageSizeUtils'

export function openImageExportDialog(onExport: (size: ImageSizeApi) => void): void {
    LemonDialog.openForm({
        title: 'Export PNG',
        width: 440,
        initialValues: { size: {} },
        errors: { size: (size) => imageSizeError(size) },
        onSubmit: ({ size }) => onExport(size),
        primaryButtonProps: { children: 'Export PNG' },
        content: (
            <LemonField name="size">
                {({ value, onChange }) => (
                    <ImageSize
                        value={value}
                        onChange={onChange}
                        description="Leave a dimension blank to size it automatically. Content fits inside the image without stretching or cropping."
                    />
                )}
            </LemonField>
        ),
    })
}
